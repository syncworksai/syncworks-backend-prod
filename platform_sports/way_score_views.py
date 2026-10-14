from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from platform_social.models import GroupMembership

from .models import SportsPlayer, SportsTeam
from .way_models import SportsPlayerExecutionTotal, SportsPlayerMetricRating, SportsTeamWeekMetric
from .way_score import team_way_score
from .way_trends import team_weekly_trend


MANAGER_ROLES = (
    GroupMembership.Role.OWNER,
    GroupMembership.Role.DIRECTOR,
    GroupMembership.Role.MANAGER,
)


def _execution_totals_payload(team):
    # Use the exact same all-games calculation as the existing Stats page so EXE%
    # and BA always compare against the PA/AB the team already sees.
    from .views import softball_player_stats

    stat_rows = softball_player_stats(team)
    stats = {int(row["player"]["id"]): row for row in stat_rows}
    season_name = team.season_name or ""
    totals = {
        row.player_id: row
        for row in SportsPlayerExecutionTotal.objects.filter(
            team=team,
            season_name=season_name,
        ).select_related("player")
    }

    players = list(
        team.players.filter(is_active=True, merged_into__isnull=True)
        .order_by("sort_order", "display_name", "id")
    )
    rows = []
    scored_points = Decimal("0")
    scored_pa = 0
    scored_hits = 0
    scored_ab = 0

    for player in players:
        stat = stats.get(player.id, {})
        total = totals.get(player.id)
        pa = int(stat.get("pa") or 0)
        ab = int(stat.get("ab") or 0)
        hits = int(stat.get("h") or 0)
        points = total.points if total else None
        exe = None
        if points is not None and pa > 0:
            exe = round(float(points) / float(pa), 3)
            scored_points += points
            scored_pa += pa
            scored_hits += hits
            scored_ab += ab
        rows.append({
            "player": {
                "id": player.id,
                "display_name": player.display_name,
                "jersey_number": player.jersey_number,
                "primary_position": player.primary_position,
            },
            "season_name": season_name,
            "execution_points": float(points) if points is not None else None,
            "execution_average": exe,
            "pa": pa,
            "ab": ab,
            "hits": hits,
            "ba": round(float(hits) / float(ab), 3) if ab else 0.0,
            "note": total.note if total else "",
            "updated_at": total.updated_at if total else None,
        })

    return {
        "season_name": season_name,
        "rows": rows,
        "team": {
            "execution_points": float(scored_points),
            "pa": scored_pa,
            "execution_average": round(float(scored_points) / float(scored_pa), 3) if scored_pa else None,
            "hits": scored_hits,
            "ab": scored_ab,
            "ba": round(float(scored_hits) / float(scored_ab), 3) if scored_ab else 0.0,
            "players_scored": sum(1 for row in rows if row["execution_points"] is not None),
        },
        "definition": "EXE% = coach-recorded execution points divided by all-games plate appearances. BA stays separate as hitting context.",
    }


class WayAnalyticsViewSet(viewsets.ViewSet):
    """Private team analytics, ratings and weekly performance for The Way We Play."""

    permission_classes = [IsAuthenticated]

    def _team_and_membership(self, request, pk):
        team = get_object_or_404(SportsTeam.objects.select_related("group"), pk=pk)
        membership = GroupMembership.objects.filter(
            group_id=team.group_id,
            user=request.user,
            status=GroupMembership.Status.ACTIVE,
        ).first()
        if not membership:
            return team, None, Response({"detail": "Active team membership required."}, status=status.HTTP_403_FORBIDDEN)
        if not bool((team.badge_rules or {}).get("way_we_play_enabled")):
            return team, membership, Response({"detail": "Way We Play analytics is not enabled for this team."}, status=status.HTTP_404_NOT_FOUND)
        return team, membership, None

    @staticmethod
    def _can_manage(membership):
        return bool(membership and membership.role in MANAGER_ROLES)

    def retrieve(self, request, pk=None):
        team, membership, error = self._team_and_membership(request, pk)
        if error:
            return error
        payload = team_way_score(team)
        manual = _execution_totals_payload(team)
        manual_by_player = {int(row["player"]["id"]): row for row in manual["rows"]}
        for row in payload.get("players", []):
            manual_row = manual_by_player.get(int(row["player"]["id"]))
            if not manual_row:
                continue
            row["execution_points"] = manual_row["execution_points"]
            row["execution_average"] = manual_row["execution_average"]
            row["batting_average"] = manual_row["ba"]
            row["all_games_pa"] = manual_row["pa"]
            row["all_games_ab"] = manual_row["ab"]
            row["all_games_hits"] = manual_row["hits"]
        payload["manual_execution"] = manual
        payload["membership_role"] = membership.role
        payload["can_award"] = self._can_manage(membership)
        return Response(payload)

    @action(detail=True, methods=["get", "post"], url_path="execution-totals")
    def execution_totals(self, request, pk=None):
        team, membership, error = self._team_and_membership(request, pk)
        if error:
            return error
        if request.method == "GET":
            payload = _execution_totals_payload(team)
            payload["can_manage"] = self._can_manage(membership)
            return Response(payload)

        if not self._can_manage(membership):
            return Response({"detail": "Manager access required."}, status=status.HTTP_403_FORBIDDEN)
        player = get_object_or_404(
            SportsPlayer,
            pk=request.data.get("player"),
            team=team,
            is_active=True,
            merged_into__isnull=True,
        )
        try:
            points = Decimal(str(request.data.get("points")))
        except (InvalidOperation, TypeError, ValueError):
            return Response({"detail": "Execution points must be a number."}, status=status.HTTP_400_BAD_REQUEST)
        if points < 0 or points > Decimal("99999"):
            return Response({"detail": "Execution points are outside the supported range."}, status=status.HTTP_400_BAD_REQUEST)
        points = points.quantize(Decimal("0.01"))
        season_name = str(request.data.get("season_name") or team.season_name or "").strip()[:80]
        note = str(request.data.get("note") or "Coach-adjusted all-games execution total").strip()[:240]
        row, _ = SportsPlayerExecutionTotal.objects.update_or_create(
            team=team,
            player=player,
            season_name=season_name,
            defaults={"points": points, "note": note, "updated_by": request.user},
        )
        payload = _execution_totals_payload(team)
        saved = next((item for item in payload["rows"] if int(item["player"]["id"]) == player.id), None)
        return Response({"saved": saved, "team": payload["team"]})

    @action(detail=True, methods=["get"], url_path="trend")
    def trend(self, request, pk=None):
        team, membership, error = self._team_and_membership(request, pk)
        if error:
            return error
        payload = team_weekly_trend(team)
        payload["can_manage"] = self._can_manage(membership)
        return Response(payload)

    @action(detail=True, methods=["get"], url_path="ratings")
    def ratings(self, request, pk=None):
        team, membership, error = self._team_and_membership(request, pk)
        if error:
            return error
        rows = SportsPlayerMetricRating.objects.filter(team=team, period_key="CURRENT").select_related("player", "rated_by")
        return Response({
            "can_manage": self._can_manage(membership),
            "scale": {"min": 1, "max": 10},
            "ratings": [
                {
                    "id": row.id,
                    "player": row.player_id,
                    "player_name": row.player.display_name,
                    "metric_key": row.metric_key,
                    "value": row.value,
                    "week_of": row.week_of.isoformat() if row.week_of else None,
                    "note": row.note,
                    "updated_at": row.updated_at,
                }
                for row in rows
            ],
        })

    @action(detail=True, methods=["post"], url_path="rate-player")
    def rate_player(self, request, pk=None):
        team, membership, error = self._team_and_membership(request, pk)
        if error:
            return error
        if not self._can_manage(membership):
            return Response({"detail": "Manager access required."}, status=status.HTTP_403_FORBIDDEN)

        player = get_object_or_404(SportsPlayer, pk=request.data.get("player"), team=team)
        metric_key = str(request.data.get("metric_key") or "").strip().upper()
        allowed = {choice[0] for choice in SportsPlayerMetricRating.Metric.choices}
        if metric_key not in allowed:
            return Response({"detail": "Choose a valid player metric."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            value = int(request.data.get("value"))
        except (TypeError, ValueError):
            return Response({"detail": "Rating must be from 1 to 10."}, status=status.HTTP_400_BAD_REQUEST)
        if value < 1 or value > 10:
            return Response({"detail": "Rating must be from 1 to 10."}, status=status.HTTP_400_BAD_REQUEST)

        raw_week = request.data.get("week_of")
        if raw_week:
            try:
                week_of = date.fromisoformat(str(raw_week))
            except (TypeError, ValueError):
                return Response({"detail": "Enter a valid week date."}, status=status.HTTP_400_BAD_REQUEST)
            week_of = week_of - timedelta(days=week_of.weekday())
        else:
            today = date.today()
            week_of = today - timedelta(days=today.weekday())

        note = str(request.data.get("note") or "").strip()[:240]
        current, _ = SportsPlayerMetricRating.objects.update_or_create(
            team=team,
            player=player,
            metric_key=metric_key,
            period_key="CURRENT",
            defaults={"value": value, "week_of": week_of, "note": note, "rated_by": request.user},
        )
        SportsPlayerMetricRating.objects.update_or_create(
            team=team,
            player=player,
            metric_key=metric_key,
            period_key=f"WEEK:{week_of.isoformat()}",
            defaults={"value": value, "week_of": week_of, "note": note, "rated_by": request.user},
        )
        return Response({
            "id": current.id,
            "player": current.player_id,
            "metric_key": current.metric_key,
            "value": current.value,
            "week_of": current.week_of,
            "note": current.note,
        })

    @action(detail=True, methods=["post"], url_path="week-target")
    def week_target(self, request, pk=None):
        team, membership, error = self._team_and_membership(request, pk)
        if error:
            return error
        if not self._can_manage(membership):
            return Response({"detail": "Manager access required."}, status=status.HTTP_403_FORBIDDEN)

        raw_week = request.data.get("week_of")
        try:
            target_week = date.fromisoformat(str(raw_week))
        except (TypeError, ValueError):
            return Response({"detail": "Enter a valid week date."}, status=status.HTTP_400_BAD_REQUEST)
        target_week = target_week - timedelta(days=target_week.weekday())

        raw_expected = request.data.get("expected_runs_per_game")
        expected = None
        if raw_expected not in (None, ""):
            try:
                expected = Decimal(str(raw_expected))
            except (InvalidOperation, TypeError, ValueError):
                return Response({"detail": "Expected runs per game must be a number."}, status=status.HTTP_400_BAD_REQUEST)
            if expected < 0 or expected > 100:
                return Response({"detail": "Expected runs per game is outside the supported range."}, status=status.HTTP_400_BAD_REQUEST)

        row, _ = SportsTeamWeekMetric.objects.update_or_create(
            team=team,
            week_of=target_week,
            defaults={
                "expected_runs_per_game": expected,
                "note": str(request.data.get("note") or "").strip()[:240],
                "updated_by": request.user,
            },
        )
        return Response({
            "id": row.id,
            "week_of": row.week_of,
            "expected_runs_per_game": row.expected_runs_per_game,
            "note": row.note,
        })
