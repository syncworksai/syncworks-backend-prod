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
from .way_models import SportsPlayerMetricRating, SportsTeamWeekMetric
from .way_score import team_way_score
from .way_trends import team_weekly_trend


MANAGER_ROLES = (
    GroupMembership.Role.OWNER,
    GroupMembership.Role.DIRECTOR,
    GroupMembership.Role.MANAGER,
)


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
        payload["membership_role"] = membership.role
        payload["can_award"] = self._can_manage(membership)
        return Response(payload)

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

        today = date.today()
        week_of = today - timedelta(days=today.weekday())
        row, _ = SportsPlayerMetricRating.objects.update_or_create(
            team=team,
            player=player,
            metric_key=metric_key,
            period_key="CURRENT",
            defaults={
                "value": value,
                "week_of": week_of,
                "note": str(request.data.get("note") or "").strip()[:240],
                "rated_by": request.user,
            },
        )
        return Response({
            "id": row.id,
            "player": row.player_id,
            "metric_key": row.metric_key,
            "value": row.value,
            "week_of": row.week_of,
            "note": row.note,
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
