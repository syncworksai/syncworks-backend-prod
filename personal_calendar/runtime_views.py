from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .github_oidc import CalendarOIDCError, verify_calendar_runtime_token
from .sync_runner import sync_due_connections


class CalendarRuntimeAPIView(APIView):
    """GitHub-OIDC protected entry point for unattended external calendar sync."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        authorization = str(request.headers.get("Authorization") or "").strip()
        if not authorization.lower().startswith("bearer "):
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        token = authorization.split(" ", 1)[1].strip()
        try:
            claims = verify_calendar_runtime_token(token)
        except CalendarOIDCError:
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        result = sync_due_connections()
        return Response(
            {
                "ok": True,
                "ran_at": timezone.now().isoformat(),
                "identity": f"github:{claims.get('run_id') or 'scheduled'}",
                **result,
            }
        )
