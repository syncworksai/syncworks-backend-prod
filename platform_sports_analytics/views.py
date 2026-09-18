from __future__ import annotations

from collections import Counter

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from platform_social.models import GroupMembership, SocialGroup
from platform_sports.models import SoftballPlateAppearance, SportsGame, SportsPlayer, SportsTeam
from platform_sports.serializers import SportsPlayerSerializer

from .models import GameCastShare, SoftballPlayContext
from .serializers import GameCastShareSerializer, SoftballPlayContextSerializer

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
OUT_RESULTS = {
    SoftballPlateAppearance.Result.OUT,
    SoftballPlateAppearance.Result.STRIKEOUT,
    SoftballPlateAppearance.Result.FIELDERS_CHOICE,
    SoftballPlateAppearance.Result.SAC_FLY,
}
AB_EXCLUDED_RESULTS = {
    SoftballPlateAppearance.Result.WALK,
    SoftballPlateAppearance.Result.SAC_FLY,
}


def _ratio(numerator, denominator):
    return round(numerator / denominator, 3) if denominator else 0.0


def can_manage_team(user, team):
    return GroupMembership.objects.filter(
        group_id=team.group_id,
        user=user,
        status=GroupMembership.Status.ACTIVE,
        role__in=MANAGEMENT_ROLES,
    ).exists()


def can_access_team(user, team):
    if team.group.visibility == SocialGroup.Visibility.PUBLIC:
        return True
    if not user or not user.is_authenticated:
        return False
    return GroupMembership.objects.filter(
        group_id=team.group_id,
        user=user,
        status=GroupMembership.Status.ACTIVE,
    ).exists()


def _empty_row(player):
    return {
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
        "roe": 0,
        "fc": 0,
        "outs": 0,
        "k": 0,
        "rbi": 0,
        "runs": 0,
        "tb": 0,
        "quality_credits": 0,
        "quality_outs": 0,
        "move_opportunities": 0,
        "move_successes": 0,
        "runners_advanced": 0,
        "spray": Counter(),
        "batted_ball": Counter(),
    }


def advanced_stats_for_team(team):
    players = list(team.players.order_by("sort_order", "display_name", "id"))
    stats = {player.id: _empty_row(player) for player in players}
    appearances = (
        SoftballPlateAppearance.objects.filter(game__team=team)
        .exclude(game__status=SportsGame.Status.CANCELLED)
        .select_related("player", "game", "advanced_context")
        .order_by("game__start_at", "sequence")
    )

    for pa in appearances:
        row = stats.setdefault(pa.player_id, _empty_row(pa.player))
        row["games"].add(pa.game_id)
        row["pa"] += 1
        row["rbi"] += int(pa.rbi or 0)
        row["runs"] += int(pa.runs_scored or 0)

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
            row["outs"] += 1
        elif pa.result == SoftballPlateAppearance.Result.REACHED_ON_ERROR:
            row["roe"] += 1
        elif pa.result == SoftballPlateAppearance.Result.FIELDERS_CHOICE:
            row["fc"] += 1
            row["outs"] += 1
        elif pa.result == SoftballPlateAppearance.Result.STRIKEOUT:
            row["k"] += 1
            row["outs"] += 1
        elif pa.result == SoftballPlateAppearance.Result.OUT:
            row["outs"] += 1

        try:
            context = pa.advanced_context
        except SoftballPlayContext.DoesNotExist:
            context = None

        if context:
            if context.had_runner_move_opportunity:
                row["move_opportunities"] += 1
                if context.runners_advanced > 0:
                    row["move_successes"] += 1
            row["runners_advanced"] += int(context.runners_advanced or 0)
            if context.spray_zone:
                row["spray"][context.spray_zone] += 1
            if context.batted_ball_type:
                row["batted_ball"][context.batted_ball_type] += 1

        productive_out = bool(
            pa.result == SoftballPlateAppearance.Result.SAC_FLY
            or (context and context.productive_out and pa.result in OUT_RESULTS)
        )
        if productive_out:
            row["quality_outs"] += 1

        if pa.result in HIT_RESULTS or pa.result == SoftballPlateAppearance.Result.WALK or productive_out:
            row["quality_credits"] += 1

    output = []
    for row in stats.values():
        ab = row["ab"]
        h = row["h"]
        bb = row["bb"]
        sf = row["sf"]
        row["g"] = len(row.pop("games"))
        row["avg"] = _ratio(h, ab)
        row["reach_avg"] = _ratio(h + bb, ab + bb)
        row["obp"] = _ratio(h + bb, ab + bb + sf)
        row["slg"] = _ratio(row["tb"], ab)
        row["ops"] = round(row["obp"] + row["slg"], 3)
        row["qpa_pct"] = _ratio(row["quality_credits"], row["pa"])
        row["move_rate"] = _ratio(row["move_successes"], row["move_opportunities"])
        row["spray"] = dict(row["spray"])
        row["batted_ball"] = dict(row["batted_ball"])
        output.append(row)
    return output


def inning_analytics_for_team(team):
    games = list(
        SportsGame.objects.filter(team=team)
        .exclude(status__in=(SportsGame.Status.CANCELLED, SportsGame.Status.SCHEDULED))
        .order_by("start_at", "id")
    )
    by_inning = {}
    for game in games:
        plays = list(game.plate_appearances.all())
        innings_seen = set()
        for pa in plays:
            inning = int(pa.inning or 1)
            innings_seen.add(inning)
            bucket = by_inning.setdefault(inning, {"inning": inning, "runs": 0, "hits": 0, "games_reached": 0})
            bucket["runs"] += int(pa.runs_scored or 0)
            if pa.result in HIT_RESULTS:
                bucket["hits"] += 1
        for inning in innings_seen:
            by_inning[inning]["games_reached"] += 1

    output = []
    for inning in sorted(by_inning):
        bucket = by_inning[inning]
        reached = bucket["games_reached"]
        output.append({
            **bucket,
            "avg_runs": _ratio(bucket["runs"], reached),
            "avg_hits": _ratio(bucket["hits"], reached),
        })
    game_count = len(games)
    total_runs = sum(int(game.runs_for or 0) for game in games)
    total_hits = SoftballPlateAppearance.objects.filter(
        game__in=games,
        result__in=HIT_RESULTS,
    ).count() if games else 0
    return {
        "games": game_count,
        "runs": total_runs,
        "hits": total_hits,
        "avg_runs_per_game": _ratio(total_runs, game_count),
        "avg_hits_per_game": _ratio(total_hits, game_count),
        "innings": output,
    }


def game_inning_grid(game):
    buckets = {}
    for pa in game.plate_appearances.order_by("sequence"):
        inning = int(pa.inning or 1)
        bucket = buckets.setdefault(
            inning,
            {"inning": inning, "runs": 0, "hits": 0, "plays": 0, "opponent_runs": 0, "opponent_hits": 0},
        )
        bucket["runs"] += int(pa.runs_scored or 0)
        bucket["plays"] += 1
        if pa.result in HIT_RESULTS:
            bucket["hits"] += 1
    for line in game.inning_lines.order_by("inning"):
        inning = int(line.inning or 1)
        bucket = buckets.setdefault(
            inning,
            {"inning": inning, "runs": 0, "hits": 0, "plays": 0, "opponent_runs": 0, "opponent_hits": 0},
        )
        bucket["opponent_runs"] = int(line.opponent_runs or 0)
        bucket["opponent_hits"] = int(line.opponent_hits or 0)
    return [buckets[key] for key in sorted(buckets)]


def team_summary(rows):
    totals = {
        key: sum(int(row.get(key, 0) or 0) for row in rows)
        for key in (
            "pa", "ab", "h", "bb", "sf", "hr", "rbi", "runs", "tb",
            "quality_credits", "quality_outs", "move_opportunities", "move_successes", "runners_advanced",
        )
    }
    return {
        **totals,
        "avg": _ratio(totals["h"], totals["ab"]),
        "reach_avg": _ratio(totals["h"] + totals["bb"], totals["ab"] + totals["bb"]),
        "obp": _ratio(totals["h"] + totals["bb"], totals["ab"] + totals["bb"] + totals["sf"]),
        "slg": _ratio(totals["tb"], totals["ab"]),
        "qpa_pct": _ratio(totals["quality_credits"], totals["pa"]),
        "move_rate": _ratio(totals["move_successes"], totals["move_opportunities"]),
    }


class PlayContextUpsertView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        pa = get_object_or_404(
            SoftballPlateAppearance.objects.select_related("game__team__group"),
            pk=request.data.get("plate_appearance"),
        )
        if not can_manage_team(request.user, pa.game.team):
            return Response({"detail": "You do not manage this sports team."}, status=status.HTTP_403_FORBIDDEN)
        context = SoftballPlayContext.objects.filter(plate_appearance=pa).first()
        serializer = SoftballPlayContextSerializer(
            context,
            data=request.data,
            partial=bool(context),
        )
        serializer.is_valid(raise_exception=True)
        if context:
            saved = serializer.save()
        else:
            saved = serializer.save(plate_appearance=pa, created_by=request.user)
        return Response(
            SoftballPlayContextSerializer(saved).data,
            status=status.HTTP_200_OK if context else status.HTTP_201_CREATED,
        )


class AdvancedTeamStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, team_id):
        team = get_object_or_404(SportsTeam.objects.select_related("group"), pk=team_id)
        if not can_access_team(request.user, team):
            return Response({"detail": "You do not have access to this sports team."}, status=status.HTTP_403_FORBIDDEN)
        if team.sport != SportsTeam.Sport.SOFTBALL:
            return Response({"detail": "Advanced analytics are currently available for softball."}, status=status.HTTP_400_BAD_REQUEST)
        players = advanced_stats_for_team(team)
        return Response({"team": team_summary(players), "players": players, "inning_analytics": inning_analytics_for_team(team)})


class PlayerSprayView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, player_id):
        player = get_object_or_404(SportsPlayer.objects.select_related("team__group"), pk=player_id)
        if not can_access_team(request.user, player.team):
            return Response({"detail": "You do not have access to this player."}, status=status.HTTP_403_FORBIDDEN)
        plays = (
            SoftballPlateAppearance.objects.filter(player=player, advanced_context__isnull=False)
            .exclude(game__status=SportsGame.Status.CANCELLED)
            .select_related("game", "advanced_context")
            .order_by("-game__start_at", "-sequence")
        )
        points = []
        for pa in plays:
            context = pa.advanced_context
            if not (context.spray_zone or context.spray_x is not None or context.spray_y is not None):
                continue
            points.append({
                "plate_appearance": pa.id,
                "game": pa.game_id,
                "game_date": pa.game.start_at,
                "opponent": pa.game.opponent_name,
                "result": pa.result,
                "inning": pa.inning,
                "zone": context.spray_zone,
                "x": context.spray_x,
                "y": context.spray_y,
                "batted_ball_type": context.batted_ball_type,
                "productive_out": context.productive_out,
                "runners_advanced": context.runners_advanced,
            })
        return Response({"player": SportsPlayerSerializer(player).data, "points": points})


class GameCastSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def _share(self, request, game):
        share, _ = GameCastShare.objects.get_or_create(
            game=game,
            defaults={"created_by": request.user},
        )
        return share

    def get(self, request, game_id):
        game = get_object_or_404(SportsGame.objects.select_related("team__group"), pk=game_id)
        if not can_manage_team(request.user, game.team):
            return Response({"detail": "A team manager controls GameCast sharing."}, status=status.HTTP_403_FORBIDDEN)
        return Response(GameCastShareSerializer(self._share(request, game)).data)

    def post(self, request, game_id):
        game = get_object_or_404(SportsGame.objects.select_related("team__group"), pk=game_id)
        if not can_manage_team(request.user, game.team):
            return Response({"detail": "A team manager controls GameCast sharing."}, status=status.HTTP_403_FORBIDDEN)
        share = self._share(request, game)
        serializer = GameCastShareSerializer(share, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class PublicGameCastView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        share = get_object_or_404(
            GameCastShare.objects.select_related("game__team__group", "game__rule_set"),
            token=token,
            enabled=True,
        )
        game = share.game
        lineup = list(game.lineup_spots.select_related("player").order_by("batting_order"))
        current_spot = next((spot for spot in lineup if spot.batting_order == game.current_batter_order), None)
        recent = list(
            game.plate_appearances.select_related("player", "advanced_context").order_by("-sequence")[:15]
        )
        plays = []
        for pa in reversed(recent):
            try:
                context = pa.advanced_context
            except SoftballPlayContext.DoesNotExist:
                context = None
            plays.append({
                "id": pa.id,
                "sequence": pa.sequence,
                "inning": pa.inning,
                "player": pa.player.display_name,
                "result": pa.result,
                "result_label": pa.get_result_display(),
                "rbi": pa.rbi,
                "runs_scored": pa.runs_scored,
                "productive_out": bool(context and context.productive_out) or pa.result == SoftballPlateAppearance.Result.SAC_FLY,
                "runners_advanced": int(context.runners_advanced or 0) if context else 0,
                "spray_zone": context.spray_zone if context else "",
                "batted_ball_type": context.batted_ball_type if context else "",
                "created_at": pa.created_at,
            })
        payload = {
            "game": {
                "id": game.id,
                "team_name": game.team.group.name,
                "opponent_name": game.opponent_name,
                "status": game.status,
                "game_type": game.game_type,
                "tournament_name": game.tournament_name,
                "round_label": game.round_label,
                "start_at": game.start_at,
                "venue_name": game.venue_name,
                "current_inning": game.current_inning,
                "outs": game.outs,
                "runs_for": game.runs_for,
                "runs_against": game.runs_against,
                "home_runs_for": game.plate_appearances.filter(result=SoftballPlateAppearance.Result.HOME_RUN).count(),
                "home_runs_against": game.home_runs_against,
                "rule_set": ({
                    "id": game.rule_set_id,
                    "name": game.rule_set.name,
                    "competition_type": game.rule_set.competition_type,
                    "home_run_rule": game.rule_set.home_run_rule,
                    "home_run_limit": game.rule_set.home_run_limit,
                    "home_run_max_ahead": game.rule_set.home_run_max_ahead,
                    "innings": game.rule_set.innings,
                } if game.rule_set_id else None),
                "inning_grid": game_inning_grid(game),
                "current_batter_order": game.current_batter_order,
                "current_batter": SportsPlayerSerializer(current_spot.player).data if current_spot else None,
                "inning_lines": [
                    {"inning": line.inning, "team_runs": line.team_runs, "opponent_runs": line.opponent_runs, "opponent_hits": line.opponent_hits}
                    for line in game.inning_lines.order_by("inning")
                ],
                "updated_at": game.updated_at,
            },
            "lineup": [
                {
                    "batting_order": spot.batting_order,
                    "defensive_position": spot.defensive_position,
                    "player": SportsPlayerSerializer(spot.player).data,
                }
                for spot in lineup
            ],
            "plays": plays,
        }
        if share.show_player_stats:
            rows = advanced_stats_for_team(game.team)
            payload["team_stats"] = team_summary(rows)
            payload["player_stats"] = rows
        return Response(payload)
