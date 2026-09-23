from __future__ import annotations

from collections import defaultdict
import hashlib

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import parsers, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from platform_social.models import EventMemberResponse, GroupMembership, SocialEvent, SocialGroup
from platform_social.views import ensure_group_event_responses, sync_social_event_calendars
from user_accounts.models import Notification
from user_accounts.services.notifications import notify

from .emails import frontend_url, send_syncworks_team_invite
from .player_merge import PlayerMergeMixin
from .player_progress import PlayerProgressMixin
from .models import (
    SoftballPlateAppearance, SportsGame, SportsGameBookPhoto, SportsGameInning,
    SportsLineupSpot, SportsPlayer, SportsSubstitution, SportsTeam,
)
from .serializers import (
    SoftballPlateAppearanceSerializer,
    SportsGameSerializer,
    SportsGameBookPhotoSerializer,
    SportsGameInningSerializer,
    SportsLineupSpotSerializer,
    SportsPlayerSerializer,
    SportsTeamSerializer,
)

User = get_user_model()

MANAGEMENT_ROLES = (
    GroupMembership.Role.OWNER,
    GroupMembership.Role.DIRECTOR,
    GroupMembership.Role.MANAGER,
)
SCOREKEEPING_ROLES = MANAGEMENT_ROLES + (
    GroupMembership.Role.SCOREKEEPER,
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


def can_score_team(user, team):
    return GroupMembership.objects.filter(
        user=user,
        group_id=team.group_id,
        status=GroupMembership.Status.ACTIVE,
        role__in=SCOREKEEPING_ROLES,
    ).exists()


def rebuild_game_from_book(game):
    appearances = list(game.plate_appearances.order_by("sequence"))
    lineup = list(game.lineup_spots.order_by("batting_order"))

    game.inning_lines.update(team_runs=0)
    inning_totals = defaultdict(int)
    for pa in appearances:
        inning_totals[int(pa.inning or 1)] += int(pa.runs_scored or 0)
    for inning_no, inning_runs in inning_totals.items():
        line, _ = SportsGameInning.objects.get_or_create(game=game, inning=inning_no)
        line.team_runs = inning_runs
        line.save(update_fields=("team_runs", "updated_at"))

    game.runs_for = sum(int(pa.runs_scored or 0) for pa in appearances)

    if appearances:
        last = appearances[-1]
        current_inning = max(1, int(last.inning or 1))
        outs_in_current = sum(
            int(pa.outs_recorded or 0)
            for pa in appearances
            if int(pa.inning or 1) == current_inning
        )
        if outs_in_current >= 3:
            game.current_inning = current_inning + 1
            game.outs = 0
        else:
            game.current_inning = current_inning
            game.outs = max(0, outs_in_current)

        current_order = lineup[0].batting_order if lineup else 1
        if lineup:
            idx = next((i for i, spot in enumerate(lineup) if spot.player_id == last.player_id), -1)
            if idx >= 0:
                current_order = lineup[(idx + 1) % len(lineup)].batting_order
        game.current_batter_order = current_order
    else:
        game.current_inning = 1
        game.outs = 0
        game.current_batter_order = lineup[0].batting_order if lineup else 1

    game.save(update_fields=("runs_for", "current_inning", "outs", "current_batter_order", "updated_at"))
    return game


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
    team_doubles = sum(row["double"] for row in stats)
    team_triples = sum(row["triple"] for row in stats)
    team_walks = sum(row["bb"] for row in stats)
    team_sf = sum(row["sf"] for row in stats)
    team_tb = sum(row["tb"] for row in stats)
    team_obp = _ratio(team_hits + team_walks, team_ab + team_walks + team_sf)
    team_slg = _ratio(team_tb, team_ab)
    return {
        "team": SportsTeamSerializer(team).data,
        "record": {"wins": wins, "losses": losses, "ties": ties, "games": len(final_games)},
        "team_stats": {
            "avg": _ratio(team_hits, team_ab),
            "hits": team_hits,
            "at_bats": team_ab,
            "plate_appearances": team_pa,
            "home_runs": team_hr,
            "doubles": team_doubles,
            "triples": team_triples,
            "walks": team_walks,
            "rbi": team_rbi,
            "obp": team_obp,
            "slg": team_slg,
            "ops": round(team_obp + team_slg, 3),
            "runs_for": sum(game.runs_for for game in final_games),
            "runs_against": sum(game.runs_against for game in final_games),
        },
        "players": SportsPlayerSerializer(team.players.order_by("sort_order", "display_name"), many=True).data,
        "player_stats": stats,
        "upcoming_games": SportsGameSerializer(
            games.filter(status=SportsGame.Status.SCHEDULED, start_at__gte=now).order_by("start_at")[:8],
            many=True,
        ).data,
        "needs_completion_games": SportsGameSerializer(
            games.filter(status=SportsGame.Status.SCHEDULED, start_at__lt=now).order_by("-start_at")[:8],
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


def home_run_is_allowed(game):
    rules = getattr(game, "rule_set", None)
    if not rules or rules.home_run_rule == "UNLIMITED":
        return True, ""
    home_runs_for = game.plate_appearances.filter(result=SoftballPlateAppearance.Result.HOME_RUN).count()
    if rules.home_run_rule == "FIXED":
        limit = rules.home_run_limit
        if limit is None or home_runs_for < limit:
            return True, ""
        return False, f"Home-run cap reached ({home_runs_for}/{limit}) for {rules.name}."
    if rules.home_run_rule == "ONE_UP":
        max_ahead = int(rules.home_run_max_ahead or 1)
        allowed_total = int(game.home_runs_against or 0) + max_ahead
        if home_runs_for < allowed_total:
            return True, ""
        return False, (
            f"One-up rule: your team has {home_runs_for} HR and the opponent has "
            f"{game.home_runs_against}. Opponent must tie/advance the HR count before another HR is legal."
        )
    return True, ""


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

    @action(detail=True, methods=["get", "post"], url_path="badge-rules")
    def badge_rules(self, request, pk=None):
        from .badge_rules import get_team_badge_rules, validate_badge_rules

        team = self.get_object()
        if request.method == "POST":
            if not can_manage_team(request.user, team):
                return Response({"detail": "Only team owners and managers can change earned reward goals."},
                                status=status.HTTP_403_FORBIDDEN)
            try:
                rules = validate_badge_rules(request.data.get("rules"))
            except serializers.ValidationError as error:
                return Response(error.detail, status=status.HTTP_400_BAD_REQUEST)
            team.badge_rules = rules
            team.save(update_fields=("badge_rules", "updated_at"))
        return Response({"team": team.pk, "rules": get_team_badge_rules(team),
                         "updated_at": team.updated_at})

    @action(detail=True, methods=["get"], url_path="badge-standings")
    def badge_standings(self, request, pk=None):
        """Compact private badge rings for lineup and Game Book; no photos/emails."""
        from .player_badges import card_progress
        team = self.get_object()
        if team.group_id not in active_group_ids(request.user):
            return Response({"detail": "Join this team to view player achievements."},
                            status=status.HTTP_403_FORBIDDEN)
        rows = []
        for player in team.players.filter(is_active=True).order_by("sort_order", "id")[:100]:
            card = card_progress(player)
            rows.append({
                "player": player.pk,
                "name": player.display_name,
                "highest_tier": max(
                    (badge["tier"] for badge in card["badges"] if badge["achieved"]),
                    key=lambda tier: {"BRONZE": 1, "SILVER": 2, "GOLD": 3, "DIAMOND": 4}[tier],
                    default="LOCKED",
                ),
                "ring_color": card["card_border"],
                "badges": [
                    {"key": badge["key"], "tier": badge["tier"],
                     "achieved": badge["achieved"], "enabled": badge["enabled"]}
                    for badge in card["badges"]
                ],
            })
        return Response({"team": team.pk, "players": rows})

    @action(detail=True, methods=["post"], url_path="remind-dues")
    def remind_dues(self, request, pk=None):
        team = self.get_object()
        if not can_manage_team(request.user, team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        from .ops_models import TeamFeeAssignment

        rows = TeamFeeAssignment.objects.filter(
            fee__team=team,
            status__in=(TeamFeeAssignment.Status.DUE, TeamFeeAssignment.Status.PARTIAL),
            player__user__isnull=False,
        ).select_related("player__user", "fee")
        totals = defaultdict(int)
        players = {}
        for row in rows:
            totals[row.player_id] += max(0, row.amount_cents - row.amount_paid_cents)
            players[row.player_id] = row.player
        sent = 0
        for player_id, amount_cents in totals.items():
            player = players[player_id]
            if amount_cents <= 0 or not player.user_id:
                continue
            notify(
                player.user,
                f"{team.group.name} payment reminder",
                f"Your current team balance is ${amount_cents / 100:.2f}. Open the team Dues tab for details and payment options.",
                {
                    "source": "SOCIAL",
                    "sync_alert": True,
                    "severity": "LOW",
                    "group_id": team.group_id,
                    "team_id": team.id,
                    "player_id": player.id,
                    "route": f"/connect/groups/{team.group_id}/sports",
                    "kind": "TEAM_DUES",
                },
                actor=request.user,
                type=Notification.TYPE_REMINDER,
            )
            sent += 1
        return Response({"sent": sent})

    @action(detail=True, methods=["get"])
    def dashboard(self, request, pk=None):
        team = self.get_object()
        return Response(team_dashboard(team))


    @action(detail=True, methods=["get"], url_path="player-center")
    def player_center(self, request, pk=None):
        from .league_models import LeagueTeamEntry
        from .league_serializers import LeagueDivisionSerializer, LeagueSeasonSerializer, SportsOrganizationSerializer
        from .league_views import division_standings, division_team_stats
        from .ops_models import SportsPlayerProfile, TeamFeeAssignment, TeamPaymentSettings
        from .ops_serializers import SportsPlayerProfileSerializer, TeamFeeAssignmentSerializer, TeamPaymentSettingsSerializer
        from .ops_views import softball_stats_summary

        team = self.get_object()
        if not user_can_access_team(request.user, team):
            return Response({"detail": "You cannot access this team."}, status=status.HTTP_403_FORBIDDEN)

        base = team_dashboard(team)
        player = team.players.filter(user=request.user, is_active=True).select_related("user").first()
        profile = None
        stats = {"all": None, "league": None, "tournament": None}
        dues = []
        balance_cents = 0

        all_rows = softball_stats_summary(team, "ALL") if team.sport == SportsTeam.Sport.SOFTBALL else []
        league_rows = softball_stats_summary(team, "LEAGUE") if team.sport == SportsTeam.Sport.SOFTBALL else []
        tournament_rows = softball_stats_summary(team, "TOURNAMENT") if team.sport == SportsTeam.Sport.SOFTBALL else []

        if player:
            profile_obj = SportsPlayerProfile.objects.filter(player=player).first()
            if profile_obj:
                profile = SportsPlayerProfileSerializer(profile_obj, context={"request": request}).data

            stats["all"] = next((row for row in all_rows if int(row["player"]["id"]) == player.id), None)
            stats["league"] = next((row for row in league_rows if int(row["player"]["id"]) == player.id), None)
            stats["tournament"] = next((row for row in tournament_rows if int(row["player"]["id"]) == player.id), None)

            due_rows = TeamFeeAssignment.objects.filter(player=player).select_related("fee", "player__user")
            dues = TeamFeeAssignmentSerializer(due_rows, many=True).data
            balance_cents = sum(
                max(0, int(row.amount_cents or 0) - int(row.amount_paid_cents or 0))
                for row in due_rows
                if row.status in (TeamFeeAssignment.Status.DUE, TeamFeeAssignment.Status.PARTIAL)
            )

        next_game = (
            team.games.filter(status=SportsGame.Status.LIVE).select_related("social_event").first()
            or team.games.filter(
                status=SportsGame.Status.SCHEDULED,
                start_at__gte=timezone.now(),
            ).select_related("social_event").order_by("start_at").first()
        )
        response = None
        if next_game and next_game.social_event_id:
            response_obj = EventMemberResponse.objects.filter(
                event_id=next_game.social_event_id,
                group_id=team.group_id,
                user=request.user,
            ).first()
            if response_obj:
                response = {
                    "id": response_obj.id,
                    "response": response_obj.response,
                    "responded_at": response_obj.responded_at,
                }

        payment_settings_obj = TeamPaymentSettings.objects.filter(team=team).first()
        payment_settings = TeamPaymentSettingsSerializer(payment_settings_obj).data if payment_settings_obj else None

        league_context = None
        entry = (
            LeagueTeamEntry.objects.filter(
                team=team,
                status=LeagueTeamEntry.Status.ACTIVE,
                division__season__is_current=True,
            )
            .select_related("division__season__organization")
            .order_by("-division__season__starts_on", "id")
            .first()
            or LeagueTeamEntry.objects.filter(team=team, status=LeagueTeamEntry.Status.ACTIVE)
            .select_related("division__season__organization")
            .order_by("-division__season__starts_on", "id")
            .first()
        )
        if entry:
            standing_rows = division_standings(entry.division)
            league_stats = division_team_stats(entry.division)
            league_context = {
                "organization": SportsOrganizationSerializer(entry.division.season.organization).data,
                "season": LeagueSeasonSerializer(entry.division.season).data,
                "division": LeagueDivisionSerializer(entry.division).data,
                "standings": standing_rows,
                "team_standing": next(
                    (row for row in standing_rows if int(row["team"]["id"]) == team.id),
                    None,
                ),
                "team_stats": next(
                    (row for row in league_stats.get("teams", []) if int(row["team"]["id"]) == team.id),
                    None,
                ),
                "leaders": league_stats.get("leaders", {}),
            }

        return Response({
            "team": base["team"],
            "record": base["record"],
            "team_stats": base["team_stats"],
            "team_player_stats": all_rows,
            "player": SportsPlayerSerializer(player).data if player else None,
            "profile": profile,
            "player_stats": stats,
            "dues": dues,
            "balance_cents": balance_cents,
            "payment_settings": payment_settings,
            "next_game": SportsGameSerializer(next_game).data if next_game else None,
            "next_game_response": response,
            "league": league_context,
        })

    @action(detail=True, methods=["get"], url_path="inning-stats")
    def inning_stats(self, request, pk=None):
        team = self.get_object()
        games = list(team.games.exclude(status=SportsGame.Status.CANCELLED).prefetch_related("plate_appearances", "inning_lines"))
        completed = [game for game in games if game.status == SportsGame.Status.FINAL]
        source = completed or games
        inning_rows = defaultdict(lambda: {"runs": 0, "hits": 0, "games": 0})
        hit_values = {
            SoftballPlateAppearance.Result.SINGLE,
            SoftballPlateAppearance.Result.DOUBLE,
            SoftballPlateAppearance.Result.TRIPLE,
            SoftballPlateAppearance.Result.HOME_RUN,
        }
        for game in source:
            appearances = list(game.plate_appearances.all())
            innings_present = set()
            for pa in appearances:
                row = inning_rows[int(pa.inning)]
                row["runs"] += int(pa.runs_scored or 0)
                row["hits"] += 1 if pa.result in hit_values else 0
                innings_present.add(int(pa.inning))
            for inning in innings_present:
                inning_rows[inning]["games"] += 1
        rows = []
        for inning, values in sorted(inning_rows.items()):
            games_count = values["games"] or 1
            rows.append({
                "inning": inning,
                "runs": values["runs"],
                "hits": values["hits"],
                "games": values["games"],
                "avg_runs": round(values["runs"] / games_count, 2),
                "avg_hits": round(values["hits"] / games_count, 2),
            })
        game_count = len(completed)
        return Response({
            "games": game_count,
            "avg_runs_per_game": round(sum(game.runs_for for game in completed) / game_count, 2) if game_count else 0,
            "avg_runs_against_per_game": round(sum(game.runs_against for game in completed) / game_count, 2) if game_count else 0,
            "innings": rows,
        })

    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None):
        team = self.get_object()
        if team.sport != SportsTeam.Sport.SOFTBALL:
            return Response({"detail": "Stat aggregation is currently available for softball."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(softball_player_stats(team))


class SportsPlayerViewSet(PlayerProgressMixin, PlayerMergeMixin, viewsets.ModelViewSet):
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
        manager = can_manage_team(self.request.user, player.team)
        owner = player.user_id == self.request.user.id
        if not manager and not owner:
            raise serializers.ValidationError("You may only edit your own player profile.")
        if "team" in serializer.validated_data and serializer.validated_data["team"].id != player.team_id:
            raise serializers.ValidationError({"team": "A player cannot be moved between teams here."})
        if owner and not manager:
            allowed = {"display_name", "bats", "throws", "primary_position"}
            blocked = [field for field in serializer.validated_data.keys() if field not in allowed]
            if blocked:
                raise serializers.ValidationError({
                    "detail": "Players may edit their name, bats/throws and primary position. Team managers control jersey and roster assignment."
                })
        serializer.save()

    @action(detail=True, methods=["post"], url_path="link-member")
    @transaction.atomic
    def link_member(self, request, pk=None):
        """Link a roster card to an already approved team member selected by the manager."""
        from .ops_models import SportsPlayerProfile

        player = self.get_object()
        if not can_manage_team(request.user, player.team):
            return Response({"detail": "Only managers can link a player's account."}, status=status.HTTP_403_FORBIDDEN)
        if not player.is_active:
            return Response({"detail": "Restore this player before linking an account."}, status=status.HTTP_409_CONFLICT)
        try:
            user_id = int(request.data.get("user") or 0)
        except (ValueError, TypeError):
            return Response({"detail": "Select an approved team member."}, status=status.HTTP_400_BAD_REQUEST)
        membership = GroupMembership.objects.filter(
            group=player.team.group, user_id=user_id,
            status=GroupMembership.Status.ACTIVE,
        ).select_related("user").first()
        if not membership:
            return Response({"detail": "The selected account must first join the team group."}, status=status.HTTP_400_BAD_REQUEST)
        if player.user_id and player.user_id != user_id:
            return Response({"detail": "This roster entry is already linked to a different account."}, status=status.HTTP_409_CONFLICT)
        if SportsPlayer.objects.filter(team=player.team, user_id=user_id).exclude(pk=player.pk).exists():
            return Response({"detail": "This account already has a player record. Use Merge to keep its game history."}, status=status.HTTP_409_CONFLICT)
        player.user_id = user_id
        player.save(update_fields=("user", "updated_at"))
        profile, _ = SportsPlayerProfile.objects.get_or_create(player=player)
        if not profile.email:
            profile.email = membership.user.email or ""
            profile.save(update_fields=("email", "updated_at"))
        return Response({"linked": True, "player": self.get_serializer(player).data})

    @action(detail=False, methods=["post"], url_path="join-mine")
    @transaction.atomic
    def join_mine(self, request):
        """Allow an approved group member to claim a matching manual roster entry or create their own."""
        from .ops_models import SportsPlayerProfile

        try:
            team_id = int(request.data.get("team") or 0)
        except (TypeError, ValueError):
            return Response({"detail": "Choose a valid team."}, status=status.HTTP_400_BAD_REQUEST)
        team = get_object_or_404(SportsTeam.objects.select_for_update(), pk=team_id)
        if not GroupMembership.objects.filter(
            group_id=team.group_id,
            user=request.user,
            status=GroupMembership.Status.ACTIVE,
        ).exists():
            return Response({"detail": "Your team invitation must be approved before joining the roster."}, status=status.HTTP_403_FORBIDDEN)

        email = str(getattr(request.user, "email", "") or "").strip().lower()
        if not email:
            return Response({"detail": "Add your account email before joining the roster."}, status=status.HTTP_400_BAD_REQUEST)
        linked = SportsPlayer.objects.filter(team=team, user=request.user).first()
        if linked:
            if not linked.is_active:
                return Response({"detail": "Ask a manager to reactivate your archived roster entry."}, status=status.HTTP_409_CONFLICT)
            return Response({"player": self.get_serializer(linked).data, "already_linked": True, "matched_existing": True})

        if SportsPlayer.objects.filter(
            team=team, manager_profile__email__iexact=email, user__isnull=False
        ).exists():
            return Response({"detail": "This email is already associated with a linked player. Ask your manager to review the roster."}, status=status.HTTP_409_CONFLICT)

        matches = list(SportsPlayer.objects.select_for_update().filter(
            team=team, user__isnull=True, is_active=True, manager_profile__email__iexact=email
        ).order_by("id")[:2])
        if len(matches) > 1:
            return Response({"detail": "Multiple roster entries use this email. Ask your manager to select your player card."}, status=status.HTTP_409_CONFLICT)

        matched_existing = bool(matches)
        if matched_existing:
            player = matches[0]
            player.user = request.user
            player.save(update_fields=("user", "updated_at"))
        else:
            full_name = f"{request.user.first_name} {request.user.last_name}".strip() or email.partition("@")[0]
            player = SportsPlayer.objects.create(
                team=team, user=request.user, display_name=full_name, created_by=request.user
            )
        SportsPlayerProfile.objects.get_or_create(player=player, defaults={"email": email})
        return Response(
            {"player": self.get_serializer(player).data, "already_linked": False, "matched_existing": matched_existing},
            status=status.HTTP_200_OK if matched_existing else status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def invite(self, request, pk=None):
        from .ops_models import SportsPlayerInvite, SportsPlayerProfile

        player = self.get_object()
        if not can_manage_team(request.user, player.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)

        email = str(request.data.get("email") or "").strip().lower()
        if not email:
            try:
                email = str(player.manager_profile.email or "").strip().lower()
            except Exception:
                email = ""
        if not email or "@" not in email:
            return Response({"detail": "Add a valid player email before sending the invitation."}, status=status.HTTP_400_BAD_REQUEST)

        duplicate = SportsPlayer.objects.filter(team=player.team, user__email__iexact=email).exclude(pk=player.pk).first()
        if duplicate:
            return Response(
                {"detail": "That email is already linked to another player on this team."},
                status=status.HTTP_409_CONFLICT,
            )

        profile, _ = SportsPlayerProfile.objects.get_or_create(player=player)
        if profile.email != email:
            profile.email = email
            profile.save(update_fields=("email", "updated_at"))

        existing_user = User.objects.filter(email__iexact=email).first()
        invite = SportsPlayerInvite.objects.filter(
            player=player,
            email=email,
            status=SportsPlayerInvite.Status.INVITED,
        ).order_by("-created_at").first()
        if not invite:
            invite = SportsPlayerInvite.objects.create(
                player=player,
                email=email,
                invited_by=request.user,
            )

        if existing_user:
            if player.user_id != existing_user.id:
                player.user = existing_user
                if not player.display_name:
                    player.display_name = f"{existing_user.first_name} {existing_user.last_name}".strip() or existing_user.email
                player.save(update_fields=("user", "display_name", "updated_at"))

            membership, membership_created = GroupMembership.objects.get_or_create(
                group=player.team.group,
                user=existing_user,
                defaults={
                    "role": GroupMembership.Role.MEMBER,
                    "status": GroupMembership.Status.INVITED,
                    "invited_by": request.user,
                },
            )
            if not membership_created and membership.status != GroupMembership.Status.ACTIVE:
                membership.role = GroupMembership.Role.MEMBER
                membership.status = GroupMembership.Status.INVITED
                membership.invited_by = request.user
                membership.save(update_fields=("role", "status", "invited_by", "updated_at"))
            notify(
                existing_user,
                f"Team invitation: {player.team.group.name}",
                f"You have been invited to join {player.team.group.name}. Open the invite to claim your player profile.",
                {
                    "source": "SOCIAL",
                    "sync_alert": True,
                    "severity": "LOW",
                    "group_id": player.team.group_id,
                    "team_id": player.team_id,
                    "player_id": player.id,
                    "route": f"/sports/team-invite/{invite.token}",
                    "kind": "TEAM_INVITE",
                },
                actor=request.user,
                type=Notification.TYPE_REMINDER,
            )

        invite_url = f"{frontend_url()}/sports/team-invite/{invite.token}"
        context = "Softball team"
        if player.team.league_name:
            context = player.team.league_name
            if player.team.division_name:
                context += f" · {player.team.division_name}"
        send_syncworks_team_invite(
            to_email=email,
            team_name=player.team.group.name,
            context_line=context,
            invite_url=invite_url,
            account_exists=bool(existing_user),
        )
        return Response({
            "email_sent": True,
            "account_found": bool(existing_user),
            "invite_url": invite_url,
            "membership_status": (
                GroupMembership.Status.INVITED if existing_user else "ACCOUNT_REQUIRED"
            ),
            "player": self.get_serializer(player).data,
        })

    @action(detail=False, methods=["get"], url_path="invite-preview", permission_classes=[AllowAny])
    def invite_preview(self, request):
        from .ops_models import SportsPlayerInvite
        token = str(request.query_params.get("token") or "").strip()
        invite = SportsPlayerInvite.objects.filter(
            token=token,
            status=SportsPlayerInvite.Status.INVITED,
        ).select_related("player__team__group", "player__user").first()
        if not invite:
            return Response({"detail": "This player invitation is no longer active."}, status=status.HTTP_404_NOT_FOUND)

        local, _, domain = invite.email.partition("@")
        masked = (local[:1] + "***@" + domain) if domain else "***"
        return Response({
            "token": str(invite.token),
            "player_id": invite.player_id,
            "player_name": invite.player.display_name,
            "jersey_number": invite.player.jersey_number,
            "position": invite.player.primary_position,
            "team_id": invite.player.team_id,
            "group_id": invite.player.team.group_id,
            "team_name": invite.player.team.group.name,
            "league_name": invite.player.team.league_name,
            "division_name": invite.player.team.division_name,
            "season_name": invite.player.team.season_name,
            "email_masked": masked,
            "account_exists": User.objects.filter(email__iexact=invite.email).exists(),
            "register_url": f"{frontend_url()}/register?email={invite.email}&next=/sports/team-invite/{invite.token}",
            "login_url": f"{frontend_url()}/login?email={invite.email}&next=/sports/team-invite/{invite.token}",
        })

    @action(detail=False, methods=["post"], url_path="claim-invite")
    @transaction.atomic
    def claim_invite(self, request):
        from .ops_models import SportsPlayerInvite, SportsPlayerProfile

        token = str(request.data.get("token") or "").strip()
        invite = SportsPlayerInvite.objects.select_for_update().filter(
            token=token,
            status=SportsPlayerInvite.Status.INVITED,
        ).select_related("player__team__group").first()
        if not invite:
            return Response({"detail": "This player invitation is no longer active."}, status=status.HTTP_404_NOT_FOUND)

        email = str(getattr(request.user, "email", "") or "").strip().lower()
        if not email or email != invite.email:
            return Response(
                {"detail": "Sign in with the email address that received this team invitation."},
                status=status.HTTP_403_FORBIDDEN,
            )

        player = invite.player
        if player.user_id and player.user_id != request.user.id:
            return Response({"detail": "This roster entry is already linked to a different account. Ask your manager to resolve the conflict."}, status=status.HTTP_409_CONFLICT)
        duplicate = SportsPlayer.objects.filter(team=player.team, user=request.user).exclude(pk=player.pk).first()
        if duplicate:
            return Response(
                {"detail": "This SyncWorks account is already linked to another player on the team."},
                status=status.HTTP_409_CONFLICT,
            )

        player.user = request.user
        if not player.display_name:
            player.display_name = f"{request.user.first_name} {request.user.last_name}".strip() or email
        player.save(update_fields=("user", "display_name", "updated_at"))

        membership, _ = GroupMembership.objects.get_or_create(
            group=player.team.group,
            user=request.user,
            defaults={
                "role": GroupMembership.Role.MEMBER,
                "status": GroupMembership.Status.ACTIVE,
                "invited_by": invite.invited_by,
            },
        )
        if membership.status != GroupMembership.Status.ACTIVE:
            membership.status = GroupMembership.Status.ACTIVE
            membership.save(update_fields=("status", "updated_at"))
        team_events = SocialEvent.objects.filter(
            organizer_group=player.team.group,
            status__in=(SocialEvent.Status.PUBLISHED, SocialEvent.Status.DRAFT),
        )
        for event in team_events:
            ensure_group_event_responses(event, player.team.group_id)
            sync_social_event_calendars(event)

        profile, _ = SportsPlayerProfile.objects.get_or_create(player=player)
        if not profile.email:
            profile.email = email
            profile.save(update_fields=("email", "updated_at"))

        invite.status = SportsPlayerInvite.Status.ACCEPTED
        invite.accepted_by = request.user
        invite.accepted_at = timezone.now()
        invite.save(update_fields=("status", "accepted_by", "accepted_at", "updated_at"))

        return Response({
            "claimed": True,
            "player": self.get_serializer(player).data,
            "route": f"/connect/groups/{player.team.group_id}/sports",
        })


    @action(detail=True, methods=["post"])
    def remind(self, request, pk=None):
        player = self.get_object()
        if not can_manage_team(request.user, player.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        if not player.user_id:
            return Response({"detail": "Link this player to a SyncWorks account first."}, status=status.HTTP_400_BAD_REQUEST)

        kind = str(request.data.get("kind") or "GENERAL").upper()
        if kind == "AVAILABILITY":
            game = player.team.games.filter(
                status=SportsGame.Status.SCHEDULED,
                start_at__gte=timezone.now(),
            ).order_by("start_at").first()
            if game:
                title = f"{player.team.group.name} game confirmation"
                body = f"Please confirm IN, OUT or SUB for {game.start_at:%b %d} vs {game.opponent_name}."
            else:
                title = f"{player.team.group.name} reminder"
                body = "Please check your team schedule and availability."
        elif kind == "DUES":
            from .ops_models import TeamFeeAssignment
            rows = TeamFeeAssignment.objects.filter(
                player=player,
                status__in=(TeamFeeAssignment.Status.DUE, TeamFeeAssignment.Status.PARTIAL),
            )
            balance = sum(max(0, row.amount_cents - row.amount_paid_cents) for row in rows)
            title = f"{player.team.group.name} payment reminder"
            body = f"Your current team balance is ${balance / 100:.2f}. Open Dues for details."
        else:
            title = f"{player.team.group.name} reminder"
            body = str(request.data.get("body") or "Please check the latest team information in SyncWorks.").strip()

        notify(
            player.user,
            title,
            body,
            {
                "source": "SOCIAL",
                "sync_alert": True,
                "severity": "LOW",
                "group_id": player.team.group_id,
                "team_id": player.team_id,
                "player_id": player.id,
                "route": f"/connect/groups/{player.team.group_id}/sports",
                "kind": f"TEAM_{kind}",
            },
            actor=request.user,
            type=Notification.TYPE_REMINDER,
        )
        return Response({"sent": True})

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
        ).select_related("team__group", "social_event", "created_by").prefetch_related("lineup_spots__player", "substitutions__outgoing_player", "substitutions__incoming_player", "inning_lines").distinct()
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
        if not can_score_team(request.user, game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        if game.status != SportsGame.Status.SCHEDULED:
            return Response({
                "detail": "The batting order is locked after the first pitch. Use Game Book substitutions or defensive changes to protect recorded stats."
            }, status=status.HTTP_409_CONFLICT)
        spots = request.data.get("spots")
        if not isinstance(spots, list):
            return Response({"detail": "spots must be a list."}, status=status.HTTP_400_BAD_REQUEST)
        player_ids = [row.get("player") for row in spots]
        orders = [row.get("batting_order") for row in spots]
        if len(player_ids) != len(set(player_ids)) or len(orders) != len(set(orders)):
            return Response({"detail": "Players and batting-order positions must be unique."}, status=status.HTTP_400_BAD_REQUEST)
        field_positions = [
            str(row.get("defensive_position") or "").strip().upper()
            for row in spots
            if str(row.get("defensive_position") or "").strip().upper()
            not in ("", "EH", "EH1", "EH2", "DH")
        ]
        if len(field_positions) != len(set(field_positions)):
            return Response({"detail": "Only one defender may occupy each field position. Use EH for additional hitters."},
                            status=status.HTTP_400_BAD_REQUEST)
        players = {p.id: p for p in SportsPlayer.objects.filter(team=game.team, id__in=player_ids, is_active=True)}
        if len(players) != len(player_ids):
            return Response({"detail": "Every lineup player must be active on this team."}, status=status.HTTP_400_BAD_REQUEST)
        if game.social_event_id:
            linked_user_ids = [player.user_id for player in players.values() if player.user_id]
            out_user_ids = set(
                EventMemberResponse.objects.filter(
                    event_id=game.social_event_id,
                    group_id=game.team.group_id,
                    user_id__in=linked_user_ids,
                    response=EventMemberResponse.Response.NO,
                ).values_list("user_id", flat=True)
            )
            if out_user_ids:
                out_names = sorted(
                    player.display_name
                    for player in players.values()
                    if player.user_id in out_user_ids
                )
                return Response(
                    {
                        "detail": "Players marked OUT cannot be added to this lineup.",
                        "players": out_names,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
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

    @action(detail=True, methods=["post"], url_path="substitute")
    def substitute(self, request, pk=None):
        game = self.get_object()
        if not can_score_team(request.user, game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        if game.status != SportsGame.Status.LIVE:
            return Response({"detail": "Substitutions are available during a live game."}, status=status.HTTP_409_CONFLICT)
        try:
            batting_order = int(request.data.get("batting_order"))
            incoming_player_id = int(request.data.get("incoming_player"))
        except (TypeError, ValueError):
            return Response({"detail": "Choose a batting slot and substitute."}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            locked = SportsGame.objects.select_for_update().get(pk=game.pk)
            spot = get_object_or_404(
                SportsLineupSpot.objects.select_for_update().select_related("player"),
                game=locked,
                batting_order=batting_order,
            )
            incoming = get_object_or_404(SportsPlayer, pk=incoming_player_id, team=locked.team, is_active=True)
            if incoming.id == spot.player_id:
                return Response({"detail": "That player is already in this batting slot."}, status=status.HTTP_400_BAD_REQUEST)
            if SportsLineupSpot.objects.filter(game=locked, player=incoming).exclude(pk=spot.pk).exists():
                return Response({"detail": "That player is already in the live lineup."}, status=status.HTTP_400_BAD_REQUEST)

            outgoing = spot.player
            new_position = str(request.data.get("defensive_position") or spot.defensive_position or incoming.primary_position or "").strip()[:40]
            SportsSubstitution.objects.create(
                game=locked,
                outgoing_player=outgoing,
                incoming_player=incoming,
                batting_order=spot.batting_order,
                defensive_position=new_position,
                inning=max(1, int(locked.current_inning or 1)),
                note=str(request.data.get("note") or "").strip()[:180],
                created_by=request.user,
            )
            spot.player = incoming
            spot.defensive_position = new_position
            spot.is_starter = False
            spot.save(update_fields=("player", "defensive_position", "is_starter", "updated_at"))

        fresh = self.get_queryset().get(pk=game.pk)
        return Response(self.get_serializer(fresh).data)

    @action(detail=True, methods=["post"], url_path="defensive-position")
    def defensive_position(self, request, pk=None):
        game = self.get_object()
        if not can_score_team(request.user, game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        try:
            player_id = int(request.data.get("player"))
        except (TypeError, ValueError):
            return Response({"detail": "Choose a lineup player."}, status=status.HTTP_400_BAD_REQUEST)
        spot = get_object_or_404(SportsLineupSpot, game=game, player_id=player_id)
        spot.defensive_position = str(request.data.get("defensive_position") or "").strip()[:40]
        spot.save(update_fields=("defensive_position", "updated_at"))
        fresh = self.get_queryset().get(pk=game.pk)
        return Response(self.get_serializer(fresh).data)

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        game = self.get_object()
        if not can_score_team(request.user, game.team):
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
        if game.gamecast_enabled:
            from .fan_notifications import notify_fans_gamecast_live
            notify_fans_gamecast_live(game)
        return Response(self.get_serializer(self.get_queryset().get(pk=game.pk)).data)

    @action(detail=True, methods=["post"])
    def play(self, request, pk=None):
        base_game = self.get_object()
        if not can_score_team(request.user, base_game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        if base_game.team.sport != SportsTeam.Sport.SOFTBALL:
            return Response({"detail": "Live play entry is currently available for softball."}, status=status.HTTP_400_BAD_REQUEST)
        result_value = str(request.data.get("result") or "").upper()
        if result_value not in SoftballPlateAppearance.Result.values:
            return Response({"detail": "Choose a valid plate-appearance result."}, status=status.HTTP_400_BAD_REQUEST)
        if result_value == SoftballPlateAppearance.Result.HOME_RUN:
            allowed, rule_message = home_run_is_allowed(base_game)
            if not allowed:
                return Response(
                    {"detail": rule_message, "code": "HOME_RUN_RULE"},
                    status=status.HTTP_409_CONFLICT,
                )
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
            inning_line, _ = SportsGameInning.objects.get_or_create(game=game, inning=game.current_inning)
            inning_line.team_runs = max(0, int(inning_line.team_runs or 0) + runs_scored)
            inning_line.save(update_fields=("team_runs", "updated_at"))
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
        if not can_score_team(request.user, base_game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        with transaction.atomic():
            game = SportsGame.objects.select_for_update().get(pk=base_game.pk)
            if game.status != SportsGame.Status.LIVE:
                return Response({"detail": "Undo is only available during a live game."}, status=status.HTTP_409_CONFLICT)
            last = game.plate_appearances.order_by("-sequence").first()
            if not last:
                return Response({"detail": "There is no play to undo."}, status=status.HTTP_409_CONFLICT)
            last.delete()
            rebuild_game_from_book(game)
        return Response(self.get_serializer(self.get_queryset().get(pk=game.pk)).data)

    @action(detail=True, methods=["post"], url_path="inning-line")
    def inning_line(self, request, pk=None):
        game = self.get_object()
        if not can_score_team(request.user, game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        try:
            inning = max(1, int(request.data.get("inning")))
            opponent_runs = max(0, int(request.data.get("opponent_runs", 0)))
            opponent_hits = max(0, int(request.data.get("opponent_hits", 0)))
        except (TypeError, ValueError):
            return Response({"detail": "Inning, runs and hits must be whole numbers."}, status=status.HTTP_400_BAD_REQUEST)
        line, _ = SportsGameInning.objects.get_or_create(game=game, inning=inning)
        line.opponent_runs = opponent_runs
        line.opponent_hits = opponent_hits
        line.save(update_fields=("opponent_runs", "opponent_hits", "updated_at"))
        game.runs_against = sum(game.inning_lines.values_list("opponent_runs", flat=True))
        game.save(update_fields=("runs_against", "updated_at"))
        return Response({
            "game": self.get_serializer(self.get_queryset().get(pk=game.pk)).data,
            "inning": SportsGameInningSerializer(line).data,
        })

    @action(detail=True, methods=["post"], url_path="opponent-score")
    def opponent_score(self, request, pk=None):
        game = self.get_object()
        if not can_score_team(request.user, game.team):
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

    @action(detail=True, methods=["post"], url_path="opponent-home-runs")
    def opponent_home_runs(self, request, pk=None):
        game = self.get_object()
        if not can_score_team(request.user, game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        try:
            value = int(request.data.get("home_runs_against"))
        except (TypeError, ValueError):
            return Response({"detail": "home_runs_against must be a whole number."}, status=status.HTTP_400_BAD_REQUEST)
        if value < 0:
            return Response({"detail": "Opponent home-run count cannot be negative."}, status=status.HTTP_400_BAD_REQUEST)
        game.home_runs_against = value
        game.save(update_fields=("home_runs_against", "updated_at"))
        return Response(self.get_serializer(self.get_queryset().get(pk=game.pk)).data)

    @action(detail=True, methods=["get", "post"], url_path="gamecast")
    def gamecast(self, request, pk=None):
        game = self.get_object()
        if not can_score_team(request.user, game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        if request.method == "POST":
            allowed = ("gamecast_enabled", "gamecast_show_batter", "gamecast_show_recent_plays")
            changed = []
            aliases = {
                "enabled": "gamecast_enabled",
                "show_batter": "gamecast_show_batter",
                "show_recent_plays": "gamecast_show_recent_plays",
            }
            for source, target in aliases.items():
                if source in request.data:
                    setattr(game, target, bool(request.data[source]))
                    changed.append(target)
            for field in allowed:
                if field in request.data:
                    setattr(game, field, bool(request.data[field]))
                    changed.append(field)
            if changed:
                game.save(update_fields=tuple(dict.fromkeys(changed + ["updated_at"])))
                if game.gamecast_enabled and game.status == SportsGame.Status.LIVE:
                    from .fan_notifications import notify_fans_gamecast_live
                    notify_fans_gamecast_live(game)
        return Response({
            "enabled": game.gamecast_enabled,
            "token": str(game.gamecast_token),
            "show_batter": game.gamecast_show_batter,
            "show_recent_plays": game.gamecast_show_recent_plays,
            "url_path": f"/gamecast/{game.gamecast_token}",
        })

    @action(detail=False, methods=["get"], url_path="gamecast-public", permission_classes=[AllowAny])
    def gamecast_public(self, request):
        token = request.query_params.get("token")
        game = get_object_or_404(
            SportsGame.objects.select_related("team__group", "rule_set").prefetch_related(
                "lineup_spots__player", "inning_lines", "plate_appearances__player"
            ),
            gamecast_token=token,
        )
        if not game.gamecast_enabled:
            return Response({"detail": "This GameCast is not currently shared."}, status=status.HTTP_404_NOT_FOUND)
        plays = list(game.plate_appearances.order_by("sequence").select_related("player"))
        inning_grid = []
        lines = {row.inning: row for row in game.inning_lines.all()}
        max_inning = max([game.current_inning, game.innings_scheduled, *lines.keys()], default=game.innings_scheduled)
        for inning in range(1, max_inning + 1):
            line = lines.get(inning)
            game_plays = [pa for pa in plays if int(pa.inning or 1) == inning]
            inning_grid.append({
                "inning": inning,
                "runs": sum(int(pa.runs_scored or 0) for pa in game_plays),
                "hits": sum(1 for pa in game_plays if pa.result in HIT_RESULTS),
                "opponent_runs": int(line.opponent_runs or 0) if line else 0,
                "opponent_hits": int(line.opponent_hits or 0) if line else 0,
            })
        current_batter = None
        if game.gamecast_show_batter:
            spot = game.lineup_spots.filter(batting_order=game.current_batter_order).select_related("player").first()
            if spot:
                # Public watch links must never expose the internal roster
                # serializer's linked user account, email, or contact details.
                current_batter = {
                    "id": spot.player_id,
                    "display_name": spot.player.display_name,
                    "jersey_number": spot.player.jersey_number,
                    "primary_position": spot.player.primary_position,
                }
        recent = []
        if game.gamecast_show_recent_plays:
            for pa in plays[-12:]:
                recent.append({
                    "id": pa.id,
                    "player": pa.player.display_name,
                    "inning": pa.inning,
                    "result": pa.result,
                    "result_label": pa.get_result_display(),
                    "outs_recorded": pa.outs_recorded,
                    "rbi": pa.rbi,
                    "runs_scored": pa.runs_scored,
                })
        group = game.team.group
        return Response({
            "game": {
                "id": game.id,
                "group_id": group.id,
                "team_name": group.name,
                "opponent_name": game.opponent_name,
                "start_at": game.start_at,
                "venue_name": game.venue_name,
                "status": game.status,
                "current_inning": game.current_inning,
                "outs": game.outs,
                "runs_for": game.runs_for,
                "runs_against": game.runs_against,
                "current_batter": current_batter,
                "inning_grid": inning_grid,
                "follower_count": group.followers.count() if hasattr(group, "followers") else 0,
                "is_following": bool(getattr(request, "user", None) and request.user.is_authenticated and group.followers.filter(user=request.user).exists()) if hasattr(group, "followers") else False,
                "rule_set": SportsGameSerializer(game, context={"request": request}).data.get("rule_set_detail"),
                "home_runs_for": game.plate_appearances.filter(result=SoftballPlateAppearance.Result.HOME_RUN).count(),
                "home_runs_against": game.home_runs_against,
            },
            "plays": recent,
        })

    @action(detail=True, methods=["post"], url_path="import-historical-book")
    @transaction.atomic
    def import_historical_book(self, request, pk=None):
        """Replace a historical game's verified book without ever keying stats to lineup slot."""
        game = SportsGame.objects.select_for_update().select_related("team").get(pk=self.get_object().pk)
        if not can_score_team(request.user, game.team):
            return Response({"detail": "You do not have scorekeeping access for this team."}, status=status.HTTP_403_FORBIDDEN)
        if game.status == SportsGame.Status.LIVE:
            return Response({"detail": "Finish or reopen/finish the live game before importing a historical book."}, status=status.HTTP_409_CONFLICT)

        plays = request.data.get("plays")
        lineup = request.data.get("lineup", [])
        if not isinstance(plays, list) or not isinstance(lineup, list):
            return Response({"detail": "lineup and plays must be lists."}, status=status.HTTP_400_BAD_REQUEST)

        player_ids = set()
        for row in lineup:
            try:
                player_ids.add(int(row.get("player")))
            except (TypeError, ValueError):
                return Response({"detail": "Every lineup row must reference an existing player ID."}, status=status.HTTP_400_BAD_REQUEST)
        for row in plays:
            try:
                player_ids.add(int(row.get("player")))
            except (TypeError, ValueError):
                return Response({"detail": "Every play must reference an existing player ID."}, status=status.HTTP_400_BAD_REQUEST)

        players = {p.id: p for p in SportsPlayer.objects.filter(team=game.team, id__in=player_ids)}
        if len(players) != len(player_ids):
            return Response(
                {"detail": "One or more scorebook names are not mapped to an existing player on this team."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_spots = []
        seen_orders, seen_players = set(), set()
        for row in lineup:
            try:
                pid = int(row["player"])
                order = int(row["batting_order"])
            except (KeyError, TypeError, ValueError):
                return Response({"detail": "Invalid lineup row."}, status=status.HTTP_400_BAD_REQUEST)
            if order < 1 or order in seen_orders or pid in seen_players:
                return Response({"detail": "Batting positions and players must be unique within a game."}, status=status.HTTP_400_BAD_REQUEST)
            seen_orders.add(order); seen_players.add(pid)
            new_spots.append(SportsLineupSpot(
                game=game, player=players[pid], batting_order=order,
                defensive_position=str(row.get("defensive_position") or "")[:40],
                is_starter=bool(row.get("is_starter", True)),
            ))

        valid_results = set(SoftballPlateAppearance.Result.values)
        new_plays = []
        for sequence, row in enumerate(plays, start=1):
            try:
                pid = int(row["player"])
                inning = max(1, int(row.get("inning") or 1))
                result = str(row["result"]).upper()
                outs_recorded = max(0, min(3, int(row.get("outs_recorded") or 0)))
                rbi = max(0, min(4, int(row.get("rbi") or 0)))
                runs_scored = max(0, min(4, int(row.get("runs_scored") or 0)))
            except (KeyError, TypeError, ValueError):
                return Response({"detail": f"Invalid play at sequence {sequence}."}, status=status.HTTP_400_BAD_REQUEST)
            if result not in valid_results:
                return Response({"detail": f"Unsupported result {result} at sequence {sequence}."}, status=status.HTTP_400_BAD_REQUEST)
            new_plays.append(SoftballPlateAppearance(
                game=game, player=players[pid], sequence=sequence, inning=inning, result=result,
                outs_recorded=outs_recorded, rbi=rbi, runs_scored=runs_scored,
                notes=str(row.get("notes") or "")[:240], created_by=request.user,
            ))

        try:
            runs_for = int(request.data.get("runs_for"))
            runs_against = int(request.data.get("runs_against"))
        except (TypeError, ValueError):
            return Response({"detail": "Verified final runs_for and runs_against are required."}, status=status.HTTP_400_BAD_REQUEST)
        if runs_for < 0 or runs_against < 0:
            return Response({"detail": "Final scores cannot be negative."}, status=status.HTTP_400_BAD_REQUEST)

        # Idempotent replace: this game is the unit of truth. Re-importing never doubles stats.
        game.plate_appearances.all().delete()
        if new_spots:
            game.lineup_spots.all().delete()
            SportsLineupSpot.objects.bulk_create(new_spots)
        SoftballPlateAppearance.objects.bulk_create(new_plays)
        rebuild_game_from_book(game)
        game.refresh_from_db()
        game.runs_for = runs_for
        game.runs_against = runs_against
        game.status = SportsGame.Status.FINAL
        game.ended_at = game.ended_at or game.start_at
        game.save(update_fields=("runs_for", "runs_against", "status", "ended_at", "updated_at"))
        sync_game_social_event(game)
        fresh = self.get_queryset().get(pk=game.pk)
        return Response(self.get_serializer(fresh).data)

    @action(detail=True, methods=["post"], url_path="delete-book")
    @transaction.atomic
    def delete_book(self, request, pk=None):
        base_game = self.get_object()
        if not can_manage_team(request.user, base_game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        game = SportsGame.objects.select_for_update().get(pk=base_game.pk)
        game.plate_appearances.all().delete()
        game.substitutions.all().delete()
        game.inning_lines.all().delete()
        game.status = SportsGame.Status.SCHEDULED
        game.current_inning = 1
        game.outs = 0
        game.current_batter_order = game.lineup_spots.order_by("batting_order").values_list("batting_order", flat=True).first() or 1
        game.runs_for = 0
        game.runs_against = 0
        game.home_runs_against = 0
        game.started_at = None
        game.ended_at = None
        game.save(update_fields=(
            "status", "current_inning", "outs", "current_batter_order", "runs_for",
            "runs_against", "home_runs_against", "started_at", "ended_at", "updated_at",
        ))
        sync_game_social_event(game)
        return Response(self.get_serializer(self.get_queryset().get(pk=game.pk)).data)

    @action(detail=True, methods=["post"], url_path="reopen")
    def reopen(self, request, pk=None):
        game = self.get_object()
        if not can_manage_team(request.user, game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        game.status = SportsGame.Status.LIVE
        game.ended_at = None
        if not game.started_at:
            game.started_at = timezone.now()
        game.save(update_fields=("status", "ended_at", "started_at", "updated_at"))
        sync_game_social_event(game)
        return Response(self.get_serializer(self.get_queryset().get(pk=game.pk)).data)

    @action(detail=True, methods=["post"])
    def finish(self, request, pk=None):
        game = self.get_object()
        if not can_score_team(request.user, game.team):
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
        try:
            from .league_views import sync_league_result_from_sports_game
            sync_league_result_from_sports_game(game)
        except Exception:
            # Team scoring must remain usable even if a legacy/non-league record has no commissioner link.
            pass
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

    @action(detail=True, methods=["patch"])
    @transaction.atomic
    def correct(self, request, pk=None):
        appearance = self.get_object()
        if not can_score_team(request.user, appearance.game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)

        allowed = {"inning", "result", "outs_recorded", "rbi", "runs_scored", "notes"}
        payload = {key: value for key, value in request.data.items() if key in allowed}
        serializer = self.get_serializer(appearance, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)
        corrected = serializer.save()

        game = SportsGame.objects.select_for_update().get(pk=appearance.game_id)
        rebuild_game_from_book(game)
        if game.status == SportsGame.Status.FINAL:
            try:
                from .league_views import sync_league_result_from_sports_game
                sync_league_result_from_sports_game(game)
            except Exception:
                pass
        fresh_game = SportsGame.objects.select_related("team__group", "rule_set").prefetch_related(
            "lineup_spots__player", "inning_lines", "plate_appearances"
        ).get(pk=game.pk)

        return Response({
            "play": self.get_serializer(corrected).data,
            "game": SportsGameSerializer(fresh_game).data,
        })


class SportsGameBookPhotoViewSet(viewsets.ModelViewSet):
    serializer_class = SportsGameBookPhotoSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        group_ids = active_group_ids(self.request.user)
        queryset = SportsGameBookPhoto.objects.filter(
            game__team__group_id__in=group_ids
        ).select_related("game__team__group", "uploaded_by")
        game_id = self.request.query_params.get("game")
        return queryset.filter(game_id=game_id) if game_id else queryset

    def create(self, request, *args, **kwargs):
        game = get_object_or_404(SportsGame.objects.select_related("team"), pk=request.data.get("game"))
        if not can_score_team(request.user, game.team):
            return Response({"detail": "Scorekeeping access is required to upload a Game Book."}, status=status.HTTP_403_FORBIDDEN)
        upload = request.FILES.get("image")
        if not upload:
            return Response({"detail": "Choose a scorebook photo."}, status=status.HTTP_400_BAD_REQUEST)
        content_type = str(getattr(upload, "content_type", "") or "").lower()
        if content_type not in ("image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"):
            return Response({"detail": "Upload a JPG, PNG, WEBP, HEIC, or HEIF image."}, status=status.HTTP_400_BAD_REQUEST)
        raw = upload.read()
        if not raw:
            return Response({"detail": "The uploaded image was empty."}, status=status.HTTP_400_BAD_REQUEST)
        if len(raw) > 8 * 1024 * 1024:
            return Response({"detail": "Scorebook photos must be 8 MB or smaller."}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        digest = hashlib.sha256(raw).hexdigest()
        photo, created = SportsGameBookPhoto.objects.get_or_create(
            game=game,
            sha256=digest,
            defaults={
                "uploaded_by": request.user,
                "original_name": str(getattr(upload, "name", "") or "")[:220],
                "content_type": content_type,
                "byte_size": len(raw),
                "image_data": raw,
                "page_label": str(request.data.get("page_label") or "")[:80],
            },
        )
        serializer = self.get_serializer(photo)
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def perform_update(self, serializer):
        photo = self.get_object()
        if not can_score_team(self.request.user, photo.game.team):
            raise serializers.ValidationError("Scorekeeping access is required.")
        serializer.save()

    def perform_destroy(self, instance):
        if not can_manage_team(self.request.user, instance.game.team):
            raise serializers.ValidationError("Team manager access is required to remove a scorebook photo.")
        instance.delete()

    @action(detail=True, methods=["get"], url_path="image")
    def image(self, request, pk=None):
        photo = self.get_object()
        response = HttpResponse(bytes(photo.image_data), content_type=photo.content_type or "image/jpeg")
        response["Content-Disposition"] = f'inline; filename="{photo.original_name or "scorebook.jpg"}"'
        response["Cache-Control"] = "private, max-age=300"
        return response
