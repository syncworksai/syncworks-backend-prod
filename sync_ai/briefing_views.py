from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.services.god_mode import is_god_mode

from .briefing import build_role_aware_briefing


class SyncRoleAwareBriefingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(build_role_aware_briefing(request.user))


class SyncGodModeBriefingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not is_god_mode(request.user):
            return Response({"detail": "Not allowed."}, status=403)

        payload = build_role_aware_briefing(request.user)
        payload["sections"] = [
            section
            for section in payload.get("sections", [])
            if section.get("id") == "god_mode"
            or str(section.get("id", "")).startswith("business_")
            or section.get("id") == "affiliate"
        ]
        return Response(payload)
