"""Owner-only pilot budget controls. Never grants more than the shared $10 cap."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .assist_pilot_views import _pilot
from .assist_pilot_budget import snapshot
from .assist_budget_policy import configure_role_limit


class SyncAssistBudgetView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        return Response(snapshot(request.user))

    def post(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        if set(request.data.keys()) != {"role", "limit_usd"}:
            return Response({"detail": "Only role and limit_usd may be configured."}, status=400)
        try:
            configure_role_limit(
                request.user, role=request.data["role"],
                limit_usd=request.data["limit_usd"],
            )
        except (ValueError, TypeError) as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(snapshot(request.user))
