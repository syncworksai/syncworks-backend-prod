"""Private team engagement: weekly RSVPs, group-chat polls and coach awards.

Weekly attendance writes existing EventMemberResponse records. This prevents
independent "poll says YES / Game Book says NO" states.
"""
from collections import Counter, defaultdict
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from platform_social.models import EventMemberResponse, GroupMembership, GroupMessage
from platform_social.views import sync_sports_lineup_availability, upsert_social_calendar_event
from user_accounts.models import Notification
from user_accounts.services.notifications import notify

from .models import SportsGame, SportsPlayer, SportsTeam
from .ops_models import SportsCoachAward, SportsTeamPoll, SportsTeamPollVote, SportsWeeklyPoll
from .views import active_group_ids, can_manage_team, sync_game_social_event


def _membership(user, team):
    return GroupMembership.objects.filter(
        user=user, group_id=team.group_id, status=GroupMembership.Status.ACTIVE
    ).exists()


def _week_start(game):
    try:
        local = timezone.localtime(game.start_at, ZoneInfo(game.timezone or "America/Chicago")).date()
    except (KeyError, ValueError):
        local = timezone.localtime(game.start_at).date()
    return local - timedelta(days=local.weekday())


def _parse_week(raw):
    try:
        parsed = date.fromisoformat(str(raw))
    except (ValueError, TypeError):
        raise serializers.ValidationError({"week_start": "Use YYYY-MM-DD for the Monday of this game week."})
    if parsed.weekday() != 0:
        raise serializers.ValidationError({"week_start": "Each weekly poll starts on Monday."})
    return parsed


def _eligible_players(team):
    members = set(GroupMembership.objects.filter(
        group_id=team.group_id, status=GroupMembership.Status.ACTIVE,
    ).values_list("user_id", flat=True))
    linked = list(team.players.filter(is_active=True, user__isnull=False).select_related("user"))
    return [player for player in linked if player.user_id in members]


def _week_games(team, week):
    return [game for game in team.games.filter(
        status__in=(SportsGame.Status.SCHEDULED, SportsGame.Status.LIVE),
        start_at__gte=timezone.now() - timedelta(hours=12),
    ).order_by("start_at", "id") if _week_start(game) == week]


def _weekly_data(team, week, poll, user, manager, games):
    members = _eligible_players(team) if manager else []
    eligible_ids = {p.user_id for p in members}
    result_games = []
    outstanding = set()
    answered = 0
    for game in games:
        existing = list(EventMemberResponse.objects.filter(
            event_id=game.social_event_id, group_id=team.group_id,
            user_id__in=eligible_ids | {user.id},
        )) if game.social_event_id else []
        by_user = {item.user_id: item.response for item in existing}
        own = by_user.get(user.id, EventMemberResponse.Response.PENDING)
        item = {
            "id": game.id, "opponent_name": game.opponent_name,
            "start_at": game.start_at, "home_away": game.home_away,
            "venue_name": game.venue_name, "city": game.city,
            "status": game.status, "response": own,
        }
        if manager:
            counts = Counter(by_user.get(p.user_id, "PENDING") for p in members)
            item["counts"] = {
                key: counts.get(key, 0) for key in ("YES", "MAYBE", "NO", "PENDING")
            }
            item["pending_players"] = [
                {"player": p.id, "name": p.display_name}
                for p in members if by_user.get(p.user_id, "PENDING") == "PENDING"
            ]
            outstanding.update(
                p.id for p in members if by_user.get(p.user_id, "PENDING") == "PENDING"
            )
        else:
            answered += own != "PENDING"
        result_games.append(item)
    data = {
        "week_start": week.isoformat(), "published": poll is not None,
        "deadline": poll.deadline if poll else None,
        "message": poll.message if poll else "",
        "games": result_games,
        "my_pending": bool(poll and not manager and answered < len(games)),
    }
    if manager:
        data["pending_players"] = len(outstanding)
        data["roster_count"] = len(members)
        data["unlinked_players"] = list(team.players.filter(
            is_active=True, user__isnull=True
        ).values("id", "display_name"))
    return data


class TeamEngagementViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def _team(self, request, pk):
        team = get_object_or_404(SportsTeam.objects.select_related("group"), pk=pk)
        if not _membership(request.user, team):
            raise serializers.ValidationError({"detail": "Join the team to access team polls."})
        return team

    @action(detail=True, methods=["get", "post"], url_path="weekly")
    def weekly(self, request, pk=None):
        team = self._team(request, pk)
        manager = can_manage_team(request.user, team)
        if request.method == "GET":
            current = timezone.localdate()
            monday = current - timedelta(days=current.weekday())
            weeks = [monday + timedelta(weeks=i) for i in range(8)]
            polls = {row.week_start: row for row in team.weekly_polls.filter(
                week_start__gte=monday, week_start__lt=monday + timedelta(weeks=8)
            )}
            upcoming = list(team.games.filter(
                status__in=(SportsGame.Status.SCHEDULED, SportsGame.Status.LIVE),
                start_at__gte=timezone.now() - timedelta(hours=12),
            ).order_by("start_at", "id"))
            grouped = defaultdict(list)
            for game in upcoming:
                grouped[_week_start(game)].append(game)
            return Response({
                "weeks": [
                    _weekly_data(team, week, polls.get(week), request.user, manager, grouped[week])
                    for week in weeks if grouped[week] and (manager or week in polls)
                ],
                "manager": manager,
            })

        if not manager:
            return Response({"detail": "Only coaches can publish an attendance poll."}, status=403)
        try:
            week = _parse_week(request.data.get("week_start"))
        except serializers.ValidationError as error:
            return Response(error.detail, status=400)
        monday = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
        if week < monday:
            return Response({"detail": "Cannot publish a past game week."}, status=400)
        games = _week_games(team, week)
        if not games:
            return Response({"detail": "Schedule at least one upcoming game that week first."}, status=400)
        raw_deadline = request.data.get("deadline")
        deadline = None
        if raw_deadline:
            field = serializers.DateTimeField()
            try:
                deadline = field.run_validation(raw_deadline)
            except serializers.ValidationError as error:
                return Response({"deadline": error.detail}, status=400)
            if deadline >= max(game.start_at for game in games):
                return Response({"deadline": "The response deadline must be before the week's games."}, status=400)
        message = str(request.data.get("message") or "").strip()[:300]
        for game in games:
            if not game.social_event_id:
                sync_game_social_event(game)
                game.refresh_from_db()
        poll, created = SportsWeeklyPoll.objects.get_or_create(
            team=team, week_start=week,
            defaults={"deadline": deadline, "message": message, "published_by": request.user},
        )
        if not created:
            poll.deadline = deadline
            poll.message = message
            poll.save(update_fields=("deadline", "message", "updated_at"))
        if created:
            GroupMessage.objects.create(
                group=team.group, author=request.user,
                body=f"Weekly game RSVP is open ({week:%b %d}). Please respond for every game in your team dashboard.",
            )
            for player in _eligible_players(team):
                notify(
                    player.user, f"{team.group.name}: games this week",
                    "Choose BOTH games, just one, or OUT from your Sports player dashboard.",
                    {
                        "source": "SPORTS", "kind": "WEEKLY_RSVP",
                        "team_id": team.id, "group_id": team.group_id,
                        "week_start": week.isoformat(), "sync_alert": True,
                        "route": f"/connect/groups/{team.group_id}/sports",
                    },
                    actor=request.user, type=Notification.TYPE_REMINDER,
                )
        return Response(
            _weekly_data(team, week, poll, request.user, True, games),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="weekly/respond")
    @transaction.atomic
    def weekly_respond(self, request, pk=None):
        team = self._team(request, pk)
        player = team.players.filter(user=request.user, is_active=True).first()
        if player is None:
            return Response({"detail": "Link your active player roster card before RSVPing."}, status=403)
        try:
            week = _parse_week(request.data.get("week_start"))
        except serializers.ValidationError as error:
            return Response(error.detail, status=400)
        poll = get_object_or_404(SportsWeeklyPoll, team=team, week_start=week)
        games = _week_games(team, week)
        if not games:
            return Response({"detail": "This week's games are no longer open for responses."}, status=409)
        if poll.deadline and timezone.now() > poll.deadline:
            return Response({"detail": "The coach's response deadline has passed. Contact your coach."}, status=409)
        supplied = request.data.get("selections")
        if not isinstance(supplied, list):
            return Response({"selections": "Provide a response for each game."}, status=400)
        valid = {"YES", "MAYBE", "NO"}
        allowed_ids = {g.id for g in games}
        chosen = {}
        for row in supplied:
            if not isinstance(row, dict):
                return Response({"selections": "Invalid response row."}, status=400)
            try:
                ident = int(row.get("game"))
            except (ValueError, TypeError):
                return Response({"selections": "Invalid game."}, status=400)
            choice = str(row.get("response") or "").upper()
            if ident not in allowed_ids or ident in chosen or choice not in valid:
                return Response({"selections": "Each game must have one YES, MAYBE or NO response."}, status=400)
            chosen[ident] = choice
        if set(chosen) != allowed_ids:
            return Response({"selections": "Respond to every game in the selected week."}, status=400)
        for game in games:
            if not game.social_event_id:
                sync_game_social_event(game)
                game.refresh_from_db()
            response, _ = EventMemberResponse.objects.update_or_create(
                event_id=game.social_event_id, group_id=team.group_id, user=request.user,
                defaults={"response": chosen[game.id], "responded_at": timezone.now()},
            )
            upsert_social_calendar_event(game.social_event, request.user.id, active=response.response != "NO")
            sync_sports_lineup_availability(response)
        return Response(
            _weekly_data(team, week, poll, request.user, False, games)
        )

    @action(detail=True, methods=["post"], url_path="weekly/remind")
    def weekly_remind(self, request, pk=None):
        team = self._team(request, pk)
        if not can_manage_team(request.user, team):
            return Response({"detail": "Only a coach may remind players."}, status=403)
        try:
            week = _parse_week(request.data.get("week_start"))
        except serializers.ValidationError as error:
            return Response(error.detail, status=400)
        poll = get_object_or_404(SportsWeeklyPoll, team=team, week_start=week)
        games = _week_games(team, week)
        sent = 0
        for player in _eligible_players(team):
            if not any(
                not game.social_event_id or not EventMemberResponse.objects.filter(
                    event_id=game.social_event_id, group_id=team.group_id,
                    user=player.user, response__in=("YES", "MAYBE", "NO")
                ).exists()
                for game in games
            ):
                continue
            if Notification.objects.filter(
                recipient=player.user,
                created_at__gte=timezone.now() - timedelta(hours=24),
                data__kind="WEEKLY_RSVP_REMINDER", data__week_start=week.isoformat(),
            ).exists():
                continue
            notify(
                player.user, f"RSVP needed: {team.group.name}",
                "Your coach is waiting for this week's game availability. Answer for each game.",
                {
                    "source": "SPORTS", "kind": "WEEKLY_RSVP_REMINDER",
                    "team_id": team.id, "group_id": team.group_id,
                    "week_start": week.isoformat(), "sync_alert": True,
                    "route": f"/connect/groups/{team.group_id}/sports",
                },
                actor=request.user, type=Notification.TYPE_REMINDER,
            )
            sent += 1
        return Response({"sent": sent, "week_start": poll.week_start.isoformat()})

    @action(detail=True, methods=["get", "post"], url_path="polls")
    def polls(self, request, pk=None):
        team = self._team(request, pk)
        if request.method == "POST":
            if not can_manage_team(request.user, team):
                return Response({"detail": "Only coaches can create a chat poll."}, status=403)
            question = str(request.data.get("question") or "").strip()
            raw = request.data.get("options")
            if len(question) < 5 or len(question) > 220:
                return Response({"question": "Enter a question between 5 and 220 characters."}, status=400)
            if not isinstance(raw, list) or not 2 <= len(raw) <= 6:
                return Response({"options": "Choose between 2 and 6 answers."}, status=400)
            options = [str(item).strip() for item in raw]
            if any(not x or len(x) > 80 for x in options) or len({x.lower() for x in options}) != len(options):
                return Response({"options": "Answers must be unique and 1–80 characters."}, status=400)
            poll = SportsTeamPoll.objects.create(
                team=team, question=question, options=options, created_by=request.user,
            )
            GroupMessage.objects.create(
                group=team.group, author=request.user,
                body=f"New team poll: {question}\nVote in the Team chat Polls section.",
            )
            return Response(_chat_poll_data(poll, request.user), status=201)
        return Response([
            _chat_poll_data(poll, request.user)
            for poll in team.chat_polls.prefetch_related("votes").order_by("-created_at")[:16]
        ])

    @action(detail=True, methods=["post"], url_path=r"polls/(?P<poll_id>\\d+)/vote")
    def poll_vote(self, request, pk=None, poll_id=None):
        team = self._team(request, pk)
        poll = get_object_or_404(SportsTeamPoll, pk=poll_id, team=team)
        if poll.is_closed or (poll.closes_at and poll.closes_at <= timezone.now()):
            return Response({"detail": "This poll is closed."}, status=409)
        try:
            index = int(request.data.get("option_index"))
        except (ValueError, TypeError):
            return Response({"option_index": "Choose one answer."}, status=400)
        if index < 0 or index >= len(poll.options):
            return Response({"option_index": "Choose one of the available answers."}, status=400)
        SportsTeamPollVote.objects.update_or_create(
            poll=poll, user=request.user, defaults={"option_index": index},
        )
        return Response(_chat_poll_data(poll, request.user))

    @action(detail=True, methods=["post"], url_path=r"polls/(?P<poll_id>\\d+)/close")
    def poll_close(self, request, pk=None, poll_id=None):
        team = self._team(request, pk)
        if not can_manage_team(request.user, team):
            return Response({"detail": "Only a coach can close a poll."}, status=403)
        poll = get_object_or_404(SportsTeamPoll, pk=poll_id, team=team)
        poll.is_closed = True
        poll.save(update_fields=("is_closed",))
        return Response(_chat_poll_data(poll, request.user))


def _chat_poll_data(poll, user):
    votes = list(poll.votes.all())
    tally = Counter(v.option_index for v in votes)
    own = next((v.option_index for v in votes if v.user_id == user.id), None)
    return {
        "id": poll.id, "question": poll.question, "options": poll.options,
        "counts": [tally.get(i, 0) for i in range(len(poll.options))],
        "total_votes": len(votes), "my_vote": own, "is_closed": poll.is_closed,
        "created_at": poll.created_at,
    }


class SportsCoachAwardSerializer(serializers.ModelSerializer):
    player_name = serializers.CharField(source="player.display_name", read_only=True)
    awarded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SportsCoachAward
        fields = ("id", "team", "player", "player_name", "kind", "title", "reason",
                  "season_name", "award_date", "game", "awarded_by",
                  "awarded_by_name", "created_at", "updated_at")
        read_only_fields = ("id", "awarded_by", "awarded_by_name", "created_at", "updated_at")

    def get_awarded_by_name(self, obj):
        return (f"{obj.awarded_by.first_name} {obj.awarded_by.last_name}".strip()
                or obj.awarded_by.email.split("@")[0])

    def validate(self, values):
        player = values.get("player", getattr(self.instance, "player", None))
        team = values.get("team", getattr(self.instance, "team", None))
        game = values.get("game", getattr(self.instance, "game", None))
        kind = values.get("kind", getattr(self.instance, "kind", None))
        if not team or not player or player.team_id != team.id:
            raise serializers.ValidationError({"player": "The player must belong to the selected team."})
        if game and game.team_id != team.id:
            raise serializers.ValidationError({"game": "Choose a game played by this team."})
        if kind == SportsCoachAward.Kind.CUSTOM and not values.get("title", getattr(self.instance, "title", "")):
            raise serializers.ValidationError({"title": "Name your custom coach award."})
        if kind == SportsCoachAward.Kind.ROOKIE_YEAR:
            season = values.get("season_name", getattr(self.instance, "season_name", ""))
            exists = SportsCoachAward.objects.filter(
                team=team, kind=kind, season_name=season, revoked_at__isnull=True,
            )
            if self.instance:
                exists = exists.exclude(pk=self.instance.pk)
            if exists.exists():
                raise serializers.ValidationError({"kind": "Rookie of the Year is already awarded this season."})
        if kind == SportsCoachAward.Kind.PLAYER_WEEK:
            awarded = values.get("award_date", getattr(self.instance, "award_date", timezone.localdate()))
            if SportsCoachAward.objects.filter(
                team=team, kind=kind, award_date=awarded, revoked_at__isnull=True,
            ).exclude(pk=self.instance.pk if self.instance else None).exists():
                raise serializers.ValidationError({"award_date": "Player of the Week has already been awarded for this date."})
        return values


class SportsCoachAwardViewSet(viewsets.ModelViewSet):
    serializer_class = SportsCoachAwardSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        queryset = SportsCoachAward.objects.filter(
            team__group_id__in=active_group_ids(self.request.user),
            revoked_at__isnull=True,
        ).select_related("team__group", "player", "awarded_by")
        team_id = self.request.query_params.get("team")
        player_id = self.request.query_params.get("player")
        if team_id:
            queryset = queryset.filter(team_id=team_id)
        if player_id:
            queryset = queryset.filter(player_id=player_id)
        return queryset

    def perform_create(self, serializer):
        team = serializer.validated_data["team"]
        if not can_manage_team(self.request.user, team):
            raise serializers.ValidationError("Only a coach may issue awards.")
        try:
            with transaction.atomic():
                award = serializer.save(
                    awarded_by=self.request.user,
                    season_name=serializer.validated_data.get("season_name") or team.season_name or str(timezone.localdate().year),
                )
        except IntegrityError:
            raise serializers.ValidationError("An award of this type already exists for that period.")
        if award.player.user_id:
            notify(
                award.player.user, f"Coach award: {award.get_kind_display()}",
                f"{team.group.name} recognized you. {award.reason}",
                {
                    "source": "SPORTS", "kind": "COACH_AWARD", "team_id": team.id,
                    "group_id": team.group_id, "player_id": award.player_id,
                    "route": f"/connect/groups/{team.group_id}/sports?tab=My%20Player",
                    "sync_alert": True,
                },
                actor=self.request.user, type=Notification.TYPE_SYSTEM,
            )

    def perform_update(self, serializer):
        award = self.get_object()
        if not can_manage_team(self.request.user, award.team):
            raise serializers.ValidationError("Only a coach may edit awards.")
        for field in ("team", "player", "awarded_by"):
            serializer.validated_data.pop(field, None)
        serializer.save()

    def perform_destroy(self, instance):
        if not can_manage_team(self.request.user, instance.team):
            raise serializers.ValidationError("Only a coach may revoke awards.")
        instance.revoked_at = timezone.now()
        instance.revoked_by = self.request.user
        instance.save(update_fields=("revoked_at", "revoked_by", "updated_at"))
