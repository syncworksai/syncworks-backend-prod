from __future__ import annotations

from datetime import date

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from platform_social.models import GroupMembership

from .models import SportsPlayer, SportsTeam
from .way_coach import FOCUS_META, coach_box_payload, snapshot_coach_box, week_start
from .way_models import SportsPlayerCoachSnapshot


MANAGER_ROLES = (
    GroupMembership.Role.OWNER,
    GroupMembership.Role.DIRECTOR,
    GroupMembership.Role.MANAGER,
)


class WayCoachViewSet(viewsets.ViewSet):
    """Private role, lineup-fit and development recommendations for The Way We Play."""

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
        can_manage = self._can_manage(membership)
        return Response(coach_box_payload(team, user=request.user, can_manage=can_manage))

    @action(detail=True, methods=["post"], url_path="snapshot")
    def snapshot(self, request, pk=None):
        team, membership, error = self._team_and_membership(request, pk)
        if error:
            return error
        if not self._can_manage(membership):
            return Response({"detail": "Manager access required."}, status=status.HTTP_403_FORBIDDEN)

        raw_week = request.data.get("week_of")
        target_week = None
        if raw_week:
            try:
                target_week = date.fromisoformat(str(raw_week))
            except (TypeError, ValueError):
                return Response({"detail": "Enter a valid week date."}, status=status.HTTP_400_BAD_REQUEST)
        saved = snapshot_coach_box(team, user=request.user, target_week=target_week)
        payload = coach_box_payload(team, user=request.user, can_manage=True)
        payload["snapshots_saved"] = len(saved)
        return Response(payload)

    @action(detail=True, methods=["post"], url_path="save-player")
    def save_player(self, request, pk=None):
        team, membership, error = self._team_and_membership(request, pk)
        if error:
            return error
        if not self._can_manage(membership):
            return Response({"detail": "Manager access required."}, status=status.HTTP_403_FORBIDDEN)

        player = get_object_or_404(
            SportsPlayer,
            pk=request.data.get("player"),
            team=team,
            is_active=True,
            merged_into__isnull=True,
        )
        raw_week = request.data.get("week_of")
        if raw_week:
            try:
                target_week = week_start(date.fromisoformat(str(raw_week)))
            except (TypeError, ValueError):
                return Response({"detail": "Enter a valid week date."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            target_week = week_start()

        snapshot_coach_box(team, user=request.user, target_week=target_week)
        snapshot = get_object_or_404(SportsPlayerCoachSnapshot, team=team, player=player, week_of=target_week)

        role_override = str(request.data.get("role_override") or "").strip()[:96]
        slots_override = str(request.data.get("slots_override") or "").strip()[:24]
        focus_override = str(request.data.get("focus_override") or "").strip().upper()[:32]
        coach_note = str(request.data.get("coach_note") or "").strip()[:640]
        if focus_override and focus_override not in FOCUS_META:
            return Response({"detail": "Choose a valid development focus."}, status=status.HTTP_400_BAD_REQUEST)

        snapshot.role_override = role_override
        snapshot.slots_override = slots_override
        snapshot.focus_override = focus_override
        snapshot.coach_note = coach_note
        snapshot.updated_by = request.user
        snapshot.save(update_fields=("role_override", "slots_override", "focus_override", "coach_note", "updated_by", "updated_at"))

        # Refresh so an overridden focus gets a matching action and run-upside model.
        payload = coach_box_payload(team, user=request.user, can_manage=True)
        saved_row = next((row for row in payload.get("rows", []) if int(row["player"]["id"]) == player.id), None)
        if saved_row:
            focus = saved_row.get("focus") or {}
            snapshot.focus_key = str(focus.get("key") or snapshot.focus_key)
            snapshot.coaching_action = str(focus.get("action") or snapshot.coaching_action)[:640]
            snapshot.projected_runs_per_game_low = focus.get("projected_runs_per_game_low") or 0
            snapshot.projected_runs_per_game_high = focus.get("projected_runs_per_game_high") or 0
            snapshot.metrics = saved_row.get("metrics") or snapshot.metrics
            snapshot.save(update_fields=(
                "focus_key", "coaching_action", "projected_runs_per_game_low",
                "projected_runs_per_game_high", "metrics", "updated_at",
            ))
            payload = coach_box_payload(team, user=request.user, can_manage=True)
            saved_row = next((row for row in payload.get("rows", []) if int(row["player"]["id"]) == player.id), saved_row)
        return Response({"saved": saved_row, "week_of": target_week.isoformat()})
