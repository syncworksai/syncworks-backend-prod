from __future__ import annotations

from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from platform_growth.services.engagement import growth_intelligence_for_user, refresh_posted_engagement
from user_accounts.services.god_mode import is_god_mode


class IsGrowthUser(BasePermission):
    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if is_god_mode(user):
            return True
        return (getattr(user, "role", "") or "").upper() == "SBO"


class GrowthIntelligenceAPIView(APIView):
    permission_classes = [IsAuthenticated, IsGrowthUser]

    def get(self, request):
        return Response(growth_intelligence_for_user(request.user))

    def post(self, request):
        refresh = refresh_posted_engagement(user=request.user, limit=50)
        return Response({"refresh": refresh, "intelligence": growth_intelligence_for_user(request.user)})
