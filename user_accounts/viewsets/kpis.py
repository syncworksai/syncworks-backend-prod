# backend/user_accounts/viewsets/kpis.py
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import PlatformDailyKpi, BusinessDailyKpi, MarketplaceCellDailyKpi
from user_accounts.serializers.kpis import (
    PlatformDailyKpiSerializer,
    BusinessDailyKpiSerializer,
    MarketplaceCellDailyKpiSerializer,
)

# ✅ Correct import location (consistent with the rest of your backend)
try:
    from user_accounts.permissions.god_mode import IsGodMode
except Exception:
    from rest_framework.permissions import BasePermission

    class IsGodMode(BasePermission):
        def has_permission(self, request, view):
            return bool(getattr(request.user, "is_superuser", False))


class PlatformDailyKpiViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = PlatformDailyKpiSerializer

    def get_queryset(self):
        days = int(self.request.query_params.get("days") or 30)
        days = max(7, min(days, 365))
        start = timezone.localdate() - timedelta(days=days - 1)
        return PlatformDailyKpi.objects.filter(day__gte=start).order_by("day")


class BusinessDailyKpiViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = BusinessDailyKpiSerializer

    def list(self, request, *args, **kwargs):
        # Scope using X-Business-Id (multi-business)
        biz_id = request.headers.get("X-Business-Id") or request.query_params.get("business_id") or ""
        if not biz_id:
            return Response({"detail": "Missing business context (X-Business-Id)."}, status=400)

        days = int(request.query_params.get("days") or 30)
        days = max(7, min(days, 365))
        start = timezone.localdate() - timedelta(days=days - 1)

        qs = BusinessDailyKpi.objects.filter(business_id=int(biz_id), day__gte=start).order_by("day")
        return Response(BusinessDailyKpiSerializer(qs, many=True).data)


class MarketplaceCellDailyKpiViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, IsGodMode]
    serializer_class = MarketplaceCellDailyKpiSerializer

    def get_queryset(self):
        days = int(self.request.query_params.get("days") or 14)
        days = max(7, min(days, 90))
        start = timezone.localdate() - timedelta(days=days - 1)

        qs = MarketplaceCellDailyKpi.objects.filter(day__gte=start)

        cat = self.request.query_params.get("category_id")
        if cat:
            qs = qs.filter(category_id=int(cat))

        zp = (self.request.query_params.get("zip_prefix") or "").strip()
        if zp:
            qs = qs.filter(zip_prefix=zp)

        return qs.order_by("day")