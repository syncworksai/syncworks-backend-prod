from __future__ import annotations

from collections import defaultdict

from django.db import transaction
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from platform_social.models import EventMemberResponse, GroupMembership, SocialEvent, SocialGroup
from platform_social.views import ensure_group_event_responses, sync_social_event_calendars

from .models import SoftballPlateAppearance, SportsGame, SportsLineupSpot, SportsPlayer, SportsTeam
from .serializers import (
    SoftballPlateAppearanceSerializer,
    SportsGameSerializer,
    SportsLineupSpotSerializer,
    SportsPlayerSerializer,
    SportsTeamSerializer,
)

MANAGEMENT_ROLES = (
    GroupMembership.Role.OWNER,
    GroupMembership.Role.DIRECTOR,
    GroupMembership.Role.MANAGER,
)

HIT_RESULTS = {
    SoftballPlateAppearance.Result.SINGLE,
    SoftballPlateAppearance.Result.DOUBLE,
    SoftballPlateAppearance.Result.TRIPLE,
    SoftballPlateAppearance.Result.HOME_RUN,
}
AB_EXCLUDED_RESULTS = {
    SoftballPlateAppearance.Result.WALK,
    SoftballPlateAppearance.Result.SAC_FLY,
}
DEFAULT_OUT_RESULTS = {
    SoftballPlateAppearance.Result.OUT,
    SoftballPlateAppearance.Result.STRIKEOUT,
    SoftballPlateAppearance.Result.FIELDERS_CHOICE,
    SoftballPlateAppearance.Result.SAC_FLY,
}


def active_group_ids(user):
    return GroupMembership.objects.filter(
        user=user,
        status=GroupMembership.Status.ACTIVE,
    ).values_list("group_id", flat=True)


def can_manage_group(user, group_id):
    return GroupMembership.objects.filter(
        user=user,
        group_id=group_id,
        status=GroupMembership.Status.ACTIVE,
        role__in=MANAGEMENT_ROLES,
    ).exists()


def can_manage_team(user, team):
    return can_manage_group(user, team.group_id)


def user_can_access_team(user, team):
    if team.group.visibility == SocialGroup.Visibility.PUBLIC:
        return True
    return GroupMembership.objects.filter(
        group_id=team.group_id,
        user=user,
        status=GroupMembership.Status.ACTIVE,
    ).exists()


def _ratio(numerator, denominator):
    return round(numerator / denominator, 3) if denominator else 0.0


def softball_player_stats(team):
    players = list(team.players.order_by("sort_order", "display_name", "id"))
    stats = {
        player.id: {
            "player": SportsPlayerSerializer(player).data,
            "games": set(),
            "pa": 0,
            "ab": 0,
            "h": 0,
            "single": 0,
            "double": 0,
            "triple": 0,
            "hr": 0,
            "bb": 0,
            "sf": 0,
            "rbi": 0,
            "tb": 0,
        }
        for player in players
    }
    appearances = SoftballPlateAppearance.objects.filter(
        game__team=team,
    ).exclude(game__status=SportsGame.Status.CANCELLED).select_related("player", "game")

    for pa in appearances:
        row = stats.setdefault(
            pa.player_id,
            {
                "player": SportsPlayerSerializer(pa.player).data,
                "games": set(), "pa": 0, "ab": 0, "h": 0, "single": 0,
                "double": 0, "triple": 0, "hr": 0, "bb": 0, "sf": 0,
                "rbi": 0, "tb": 0,
            },
        )
        row["games"].add(pa.game_id)
        row["pa"] += 1
        row["rbi"] += pa.rbi
        if pa.result not in AB_EXCLUDED_RESULTS:
            row["ab"] += 1
        if pa.result in HIT_RESULTS:
            row["h"] += 1
        if pa.result == SoftballPlateAppearance.Result.SINGLE:
            row["single"] += 1
            row["tb"] += 1
        elif pa.result == SoftballPlateAppearance.Result.DOUBLE:
            row["double"] += 1
            row["tb"] += 2
        elif pa.result == SoftballPlateAppearance.Result.TRIPLE:
            row["triple"] += 1
            row["tb"] += 3
        elif pa.result == SoftballPlateAppearance.Result.HOME_RUN:
            row["hr"] += 1
            row["tb"] += 4
        elif pa.result == SoftballPlateAppearance.Result.WALK:
            row["bb"] += 1
        elif pa.result == SoftballPlateAppearance.Result.SAC_FLY:
            row["sf"] += 1

    output = []
    for row in stats.values():
        ab = row["ab"]
        h = row["h"]
        bb = row["bb"]
        sf = row["sf"]
        row["g"] = len(row.pop("games"))
        row["avg"] = _ratio(h, ab)
        row["obp"] = _ratio(h + bb, ab + bb + sf)
        row["slg"] = _ratio(row["tb"], ab)
        row["ops"] = round(row["obp"] + row["slg"], 3)
        output.append(row)
    return output


def team_dashboard(team):
    now = timezone.now()
    games = team.games.select_related("social_event").prefetch_related("lineup_spots__player")
    final_games = list(games.filter(status=SportsGame.Status.FINAL))
    wins = sum(1 for game in final_games if game.runs_for > game.runs_against)
    losses = sum(1 for game in final_games if game.runs_for < game.runs_against)
    ties = sum(1 for game in final_games if game.runs_for == game.runs_against)
    stats = softball_player_stats(team) if team.sport == SportsTeam.Sport.SOFTBALL else []
    team_ab = sum(row["ab"] for row in stats)
    team_hits = sum(row["h"] for row in stats)
    team_pa = sum(row["pa"] for row in stats)
    team_hr = sum(row["hr"] for row in stats)
    team_rbi = sum(row["rbi"] for row in stats)
    return {
        "team": SportsTeamSerializer(team).data,
        "record": {"wins": wins, "losses": losses, "ties": ties, "games": len(final_games)},
        "team_stats": {
            "avg": _ratio(team_hits, team_ab),
            "hits": team_hits,
            "at_bats": team_ab,
            "plate_appearances": team_pa,
            "home_runs": team_hr,
            "rbi": team_rbi,
            "runs_for": sum(game.runs_for for game in final_games),
            "runs_against": sum(game.runs_against for game in final_games),
        },
        "players": SportsPlayerSerializer(team.players.order_by("sort_order", "display_name"), many=True).data,
        "player_stats": stats,
        "upcoming_games": SportsGameSerializer(
            games.filter(status=SportsGame.Status.SCHEDULED, start_at__gte=now).order_by("start_at")[:8],
            many=True,
        ).data,
        "recent_games": SportsGameSerializer(
            games.filter(status=SportsGame.Status.FINAL).order_by("-start_at")[:8],
            many=True,
        ).data,
        "live_games": SportsGameSerializer(games.filter(status=SportsGame.Status.LIVE), many=True).data,
    }


def sync_game_social_event(game):
    event_status = SocialEvent.Status.PUBLISHED
    if game.status == SportsGame.Status.FINAL:
        event_status = SocialEvent.Status.COMPLETED
    elif game.status == SportsGame.Status.CANCELLED:
        event_status = SocialEvent.Status.CANCELLED

    title = f"{game.team.group.name} vs {game.opponent_name}"
    details = []
    if game.game_type == SportsGame.GameType.TOURNAMENT and game.tournament_name:
        details.append(game.tournament_name)
    if game.round_label:
        details.append(game.round_label)
    if game.notes:
        details.append(game.notes)
    defaults = {
        "organizer_group": game.team.group,
        "title": title,
        "description": "\n".join(details),
        "start_at": game.start_at,
        "end_at": game.end_at,
        "timezone": game.timezone,
        "venue_name": game.venue_name,
        "address_line1": game.address_line1,
        "city": game.city,
        "state": game.state,
        "status": event_status,
        "rules": f"{game.get_game_type_display()} · {game.get_home_away_display()}",
    }
    if game.social_event_id:
        event = game.social_event
        for field, value in defaults.items():
            setattr(event, field, value)
        event.version += 1
        event.save()
    else:
        event = SocialEvent.objects.create(created_by=game.created_by, **defaults)
        game.social_event = event
        game.save(update_fields=("social_event", "updated_at"))
        ensure_group_event_responses(event, game.team.group_id)
    sync_social_event_calendars(event)
    return event


class SportsTeamViewSet(viewsets.ModelViewSet):
    serializer_class = SportsTeamSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        group_ids = active_group_ids(self.request.user)
        return SportsTeam.objects.filter(
            Q(group_id__in=group_ids) | Q(group__visibility=SocialGroup.Visibility.PUBLIC)
        ).select_related("group", "created_by").distinct()

    def perform_create(self, serializer):
        group = serializer.validated_data["group"]
        if group.kind != SocialGroup.Kind.TEAM:
            raise serializers.ValidationError("Choose a Social group with kind TEAM.")
        if not can_manage_group(self.request.user, group.id):
            raise serializers.ValidationError("You do not manage this team group.")
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        team = self.get_object()
        if not can_manage_team(self.request.user, team):
            raise serializers.ValidationError("You do not manage this sports team.")
        if "group" in serializer.validated_data and serializer.validated_data["group"].id != team.group_id:
            raise serializers.ValidationError({"group": "A sports team cannot be moved to another Social group."})
        serializer.save()

    @action(detail=False, methods=["post"])
    def ensure(self, request):
        group = get_object_or_404(SocialGroup, pk=request.data.get("group"), is_active=True)
        if group.kind != SocialGroup.Kind.TEAM:
            return Response({"detail": "Sports setup requires a Social TEAM group."}, status=status.HTTP_400_BAD_REQUEST)
        if not can_manage_group(request.user, group.id):
            return Response({"detail": "A team owner/director/manager must set up Sports."}, status=status.HTTP_403_FORBIDDEN)
        sport = str(request.data.get("sport") or SportsTeam.Sport.SOFTBALL).upper()
        if sport not in SportsTeam.Sport.values:
            return Response({"detail": "Unsupported sport."}, status=status.HTTP_400_BAD_REQUEST)
        team, created = SportsTeam.objects.get_or_create(
            group=group,
            defaults={"sport": sport, "created_by": request.user},
        )
        return Response(self.get_serializer(team).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def dashboard(self, request, pk=None):
        team = self.get_object()
        return Response(team_dashboard(team))

    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None):
        team = self.get_object()
        if team.sport != SportsTeam.Sport.SOFTBALL:
            return Response({"detail": "Stat aggregation is currently available for softball."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(softball_player_stats(team))


class SportsPlayerViewSet(viewsets.ModelViewSet):
    serializer_class = SportsPlayerSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        group_ids = active_group_ids(self.request.user)
        queryset = SportsPlayer.objects.filter(
            Q(team__group_id__in=group_ids) | Q(team__group__visibility=SocialGroup.Visibility.PUBLIC)
        ).select_related("team__group", "user", "created_by").distinct()
        team_id = self.request.query_params.get("team")
        return queryset.filter(team_id=team_id) if team_id else queryset

    def perform_create(self, serializer):
        team = serializer.validated_data["team"]
        if not can_manage_team(self.request.user, team):
            raise serializers.ValidationError("You do not manage this sports team.")
        user = serializer.validated_data.get("user")
        if user and not GroupMembership.objects.filter(
            group_id=team.group_id,
            user=user,
            status__in=(GroupMembership.Status.ACTIVE, GroupMembership.Status.INVITED),
        ).exists():
            raise serializers.ValidationError({"user": "Invite this SyncWorks user to the Social team first."})
        display_name = str(serializer.validated_data.get("display_name") or "").strip()
        if user and not display_name:
            display_name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip() or user.email
        serializer.save(created_by=self.request.user, display_name=display_name)

    def perform_update(self, serializer):
        player = self.get_object()
        if not can_manage_team(self.request.user, player.team):
            raise serializers.ValidationError("You do not manage this sports team.")
        if "team" in serializer.validated_data and serializer.validated_data["team"].id != player.team_id:
            raise serializers.ValidationError({"team": "A player cannot be moved between teams here."})
        serializer.save()

    def perform_destroy(self, instance):
        if not can_manage_team(self.request.user, instance.team):
            raise serializers.ValidationError("You do not manage this sports team.")
        instance.is_active = False
        instance.save(update_fields=("is_active", "updated_at"))


class SportsGameViewSet(viewsets.ModelViewSet):
    serializer_class = SportsGameSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        group_ids = active_group_ids(self.request.user)
        queryset = SportsGame.objects.filter(
            Q(team__group_id__in=group_ids) | Q(team__group__visibility=SocialGroup.Visibility.PUBLIC)
        ).select_related("team__group", "social_event", "created_by").prefetch_related("lineup_spots__player").distinct()
        team_id = self.request.query_params.get("team")
        return queryset.filter(team_id=team_id) if team_id else queryset

    def perform_create(self, serializer):
        team = serializer.validated_data["team"]
        if not can_manage_team(self.request.user, team):
            raise serializers.ValidationError("You do not manage this sports team.")
        game = serializer.save(created_by=self.request.user)
        sync_game_social_event(game)

    def perform_update(self, serializer):
        game = self.get_object()
        if not can_manage_team(self.request.user, game.team):
            raise serializers.ValidationError("You do not manage this sports team.")
        if "team" in serializer.validated_data and serializer.validated_data["team"].id != game.team_id:
            raise serializers.ValidationError({"team": "A game cannot be moved to another team."})
        game = serializer.save()
        sync_game_social_event(game)

    def perform_destroy(self, instance):
        if not can_manage_team(self.request.user, instance.team):
            raise serializers.ValidationError("You do not manage this sports team.")
        instance.status = SportsGame.Status.CANCELLED
        instance.save(update_fields=("status", "updated_at"))
        sync_game_social_event(instance)

    @action(detail=True, methods=["post"], url_path="set-lineup")
    def set_lineup(self, request, pk=None):
        game = self.get_object()
        if not can_manage_team(request.user, game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        spots = request.data.get("spots")
        if not isinstance(spots, list):
            return Response({"detail": "spots must be a list."}, status=status.HTTP_400_BAD_REQUEST)
        player_ids = [row.get("player") for row in spots]
        orders = [row.get("batting_order") for row in spots]
        if len(player_ids) != len(set(player_ids)) or len(orders) != len(set(orders)):
            return Response({"detail": "Players and batting-order positions must be unique."}, status=status.HTTP_400_BAD_REQUEST)
        players = {p.id: p for p in SportsPlayer.objects.filter(team=game.team, id__in=player_ids, is_active=True)}
        if len(players) != len(player_ids):
            return Response({"detail": "Every lineup player must be active on this team."}, status=status.HTTP_400_BAD_REQUEST)
        new_spots = []
        try:
            for row in spots:
                order = int(row.get("batting_order"))
                if order < 1:
                    raise ValueError
                new_spots.append(
                    SportsLineupSpot(
                        game=game,
                        player=players[int(row.get("player"))],
                        batting_order=order,
                        defensive_position=str(row.get("defensive_position") or "").strip(),
                        is_starter=bool(row.get("is_starter", True)),
                    )
                )
        except (TypeError, ValueError, KeyError):
            return Response({"detail": "Invalid lineup data."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            game.lineup_spots.all().delete()
            SportsLineupSpot.objects.bulk_create(new_spots)
            game.current_batter_order = min(orders) if orders else 1
            game.save(update_fields=("current_batter_order", "updated_at"))
        fresh = self.get_queryset().get(pk=game.pk)
        return Response(self.get_serializer(fresh).data)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        game = self.get_object()
        if not can_manage_team(request.user, game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        lineup = list(game.lineup_spots.order_by("batting_order"))
        if not lineup:
            return Response({"detail": "Build a lineup before starting the game."}, status=status.HTTP_400_BAD_REQUEST)
        game.status = SportsGame.Status.LIVE
        game.started_at = game.started_at or timezone.now()
        game.current_inning = max(game.current_inning, 1)
        game.outs = 0
        game.current_batter_order = lineup[0].batting_order
        game.save(update_fields=("status", "started_at", "current_inning", "outs", "current_batter_order", "updated_at"))
        sync_game_social_event(game)
        return Response(self.get_serializer(self.get_queryset().get(pk=game.pk)).data)

    @action(detail=True, methods=["post"])
    def play(self, request, pk=None):
        base_game = self.get_object()
        if not can_manage_team(request.user, base_game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        if base_game.team.sport != SportsTeam.Sport.SOFTBALL:
            return Response({"detail": "Live play entry is currently available for softball."}, status=status.HTTP_400_BAD_REQUEST)
        result_value = str(request.data.get("result") or "").upper()
        if result_value not in SoftballPlateAppearance.Result.values:
            return Response({"detail": "Choose a valid plate-appearance result."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            rbi = max(0, int(request.data.get("rbi", 0)))
            runs_scored = max(0, int(request.data.get("runs_scored", 0)))
        except (TypeError, ValueError):
            return Response({"detail": "RBI and runs must be whole numbers."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            game = SportsGame.objects.select_for_update().select_related("team__group").get(pk=base_game.pk)
            if game.status != SportsGame.Status.LIVE:
                return Response({"detail": "Start the game before recording plays."}, status=status.HTTP_409_CONFLICT)
            lineup = list(SportsLineupSpot.objects.filter(game=game).select_related("player").order_by("batting_order"))
            if not lineup:
                return Response({"detail": "This game has no lineup."}, status=status.HTTP_400_BAD_REQUEST)
            current_index = next((i for i, spot in enumerate(lineup) if spot.batting_order == game.current_batter_order), 0)
            spot = lineup[current_index]
            default_outs = 1 if result_value in DEFAULT_OUT_RESULTS else 0
            try:
                outs_recorded = int(request.data.get("outs_recorded", default_outs))
            except (TypeError, ValueError):
                return Response({"detail": "outs_recorded must be a whole number."}, status=status.HTTP_400_BAD_REQUEST)
            if outs_recorded < 0 or outs_recorded > (3 - game.outs):
                return Response({"detail": "Outs on this play exceed the outs remaining in the inning."}, status=status.HTTP_400_BAD_REQUEST)
            sequence = (SoftballPlateAppearance.objects.filter(game=game).aggregate(max_seq=Max("sequence"))["max_seq"] or 0) + 1
            pa = SoftballPlateAppearance.objects.create(
                game=game,
                player=spot.player,
                sequence=sequence,
                inning=game.current_inning,
                result=result_value,
                outs_recorded=outs_recorded,
                rbi=rbi,
                runs_scored=runs_scored,
                notes=str(request.data.get("notes") or "").strip(),
                created_by=request.user,
            )
            game.runs_for += runs_scored
            game.outs += outs_recorded
            if game.outs >= 3:
                game.outs = 0
                game.current_inning += 1
            game.current_batter_order = lineup[(current_index + 1) % len(lineup)].batting_order
            game.save(update_fields=("runs_for", "outs", "current_inning", "current_batter_order", "updated_at"))
        fresh = self.get_queryset().get(pk=game.pk)
        return Response({"game": self.get_serializer(fresh).data, "play": SoftballPlateAppearanceSerializer(pa).data}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def undo(self, request, pk=None):
        base_game = self.get_object()
        if not can_manage_team(request.user, base_game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        with transaction.atomic():
            game = SportsGame.objects.select_for_update().get(pk=base_game.pk)
            if game.status != SportsGame.Status.LIVE:
                return Response({"detail": "Undo is only available during a live game."}, status=status.HTTP_409_CONFLICT)
            last = game.plate_appearances.order_by("-sequence").first()
            if not last:
                return Response({"detail": "There is no play to undo."}, status=status.HTTP_409_CONFLICT)
            last.delete()
            appearances = list(game.plate_appearances.order_by("sequence"))
            lineup = list(game.lineup_spots.order_by("batting_order"))
            runs_for = 0
            inning = 1
            outs = 0
            last_player_id = None
            for pa in appearances:
                runs_for += pa.runs_scored
                outs += pa.outs_recorded
                if outs >= 3:
                    outs = 0
                    inning += 1
                last_player_id = pa.player_id
            current_order = lineup[0].batting_order if lineup else 1
            if last_player_id and lineup:
                idx = next((i for i, spot in enumerate(lineup) if spot.player_id == last_player_id), -1)
                if idx >= 0:
                    current_order = lineup[(idx + 1) % len(lineup)].batting_order
            game.runs_for = runs_for
            game.current_inning = inning
            game.outs = outs
            game.current_batter_order = current_order
            game.save(update_fields=("runs_for", "current_inning", "outs", "current_batter_order", "updated_at"))
        return Response(self.get_serializer(self.get_queryset().get(pk=game.pk)).data)

    @action(detail=True, methods=["post"], url_path="opponent-score")
    def opponent_score(self, request, pk=None):
        game = self.get_object()
        if not can_manage_team(request.user, game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        try:
            score = int(request.data.get("runs_against"))
        except (TypeError, ValueError):
            return Response({"detail": "runs_against must be a whole number."}, status=status.HTTP_400_BAD_REQUEST)
        if score < 0:
            return Response({"detail": "Score cannot be negative."}, status=status.HTTP_400_BAD_REQUEST)
        game.runs_against = score
        game.save(update_fields=("runs_against", "updated_at"))
        return Response(self.get_serializer(self.get_queryset().get(pk=game.pk)).data)

    @action(detail=True, methods=["post"])
    def finish(self, request, pk=None):
        game = self.get_object()
        if not can_manage_team(request.user, game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        for field in ("runs_for", "runs_against"):
            if field in request.data:
                try:
                    value = int(request.data[field])
                except (TypeError, ValueError):
                    return Response({"detail": f"{field} must be a whole number."}, status=status.HTTP_400_BAD_REQUEST)
                if value < 0:
                    return Response({"detail": "Scores cannot be negative."}, status=status.HTTP_400_BAD_REQUEST)
                setattr(game, field, value)
        game.status = SportsGame.Status.FINAL
        game.ended_at = timezone.now()
        game.save(update_fields=("runs_for", "runs_against", "status", "ended_at", "updated_at"))
        sync_game_social_event(game)
        return Response(self.get_serializer(self.get_queryset().get(pk=game.pk)).data)


class SoftballPlateAppearanceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SoftballPlateAppearanceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        group_ids = active_group_ids(self.request.user)
        queryset = SoftballPlateAppearance.objects.filter(
            Q(game__team__group_id__in=group_ids) | Q(game__team__group__visibility=SocialGroup.Visibility.PUBLIC)
        ).select_related("game__team__group", "player", "created_by").distinct()
        game_id = self.request.query_params.get("game")
        return queryset.filter(game_id=game_id) if game_id else queryset
