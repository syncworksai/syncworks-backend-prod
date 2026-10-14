from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from platform_social.models import GroupMembership

from .models import SportsTeam
from .way_score import team_way_score


class WayAnalyticsViewSet(viewsets.ViewSet):
    """Private team analytics for The Way We Play.

    The feature flag lives inside SportsTeam.badge_rules so it survives a group/team rename.
    Only an ACTIVE member of the exact SocialGroup may read the scorecard.
    """

    permission_classes = [IsAuthenticated]

    def retrieve(self, request, pk=None):
        team = get_object_or_404(SportsTeam.objects.select_related("group"), pk=pk)
        membership = GroupMembership.objects.filter(
            group_id=team.group_id,
            user=request.user,
            status=GroupMembership.Status.ACTIVE,
        ).first()
        if not membership:
            return Response({"detail": "Active team membership required."}, status=status.HTTP_403_FORBIDDEN)

        if not bool((team.badge_rules or {}).get("way_we_play_enabled")):
            return Response({"detail": "Way We Play analytics is not enabled for this team."}, status=status.HTTP_404_NOT_FOUND)

        payload = team_way_score(team)
        payload["membership_role"] = membership.role
        payload["can_award"] = membership.role in (
            GroupMembership.Role.OWNER,
            GroupMembership.Role.DIRECTOR,
            GroupMembership.Role.MANAGER,
        )
        return Response(payload)
