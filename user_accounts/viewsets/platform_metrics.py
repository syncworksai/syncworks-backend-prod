# backend/user_accounts/viewsets/platform_metrics.py
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

# ✅ Correct import location (matches your other platform viewsets)
try:
    from user_accounts.permissions.god_mode import IsGodMode
except Exception:
    # ultra-safe fallback so this file never hard-crashes in import-time
    from rest_framework.permissions import BasePermission

    class IsGodMode(BasePermission):
        def has_permission(self, request, view):
            return bool(getattr(request.user, "is_superuser", False))


from user_accounts.services.god_mode_metrics import resolve_range, cached_summary, alerts_pack


class PlatformMetricsSummaryAPIView(APIView):
    """
    GET /api/v1/platform/metrics/summary/?days=30
    or  /api/v1/platform/metrics/summary/?start=YYYY-MM-DD&end=YYYY-MM-DD
    """
    permission_classes = [IsAuthenticated, IsGodMode]

    def get(self, request):
        try:
            start = request.query_params.get("start")
            end = request.query_params.get("end")
            days = request.query_params.get("days")

            start_d, end_d = resolve_range(start=start, end=end, days=days, default_days=30)
            data = cached_summary(start_d, end_d)
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            # ✅ return a readable payload instead of a silent 500
            return Response(
                {
                    "detail": "Platform metrics summary failed.",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PlatformMetricsAlertsAPIView(APIView):
    """
    GET /api/v1/platform/metrics/alerts/
    """
    permission_classes = [IsAuthenticated, IsGodMode]

    def get(self, request):
        try:
            return Response(alerts_pack(), status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {
                    "detail": "Platform metrics alerts failed.",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )