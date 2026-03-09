# backend/user_accounts/viewsets/pm_properties.py
from __future__ import annotations

from django.db.models import Q, Count
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from user_accounts.models.pm_property import PMProperty
from user_accounts.models.pm_unit import PMUnit
from user_accounts.serializers.pm_properties import PMPropertySerializer
from user_accounts.viewsets.pm_common import get_business_from_header, require_business_access


class PMPropertyViewSet(viewsets.ModelViewSet):
    """
    Supports scalable search for large portfolios.

    Query params:
      - q: fuzzy search across name/address/city/state/zip
      - city, zip, property_type, status: exact filters
      - ordering: one of name, city, state, zip, created_at, updated_at
        (prefix with '-' for desc)
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PMPropertySerializer

    ALLOWED_ORDER_FIELDS = {"name", "city", "state", "zip", "created_at", "updated_at"}

    def get_queryset(self):
        biz = get_business_from_header(self.request)
        require_business_access(self.request.user, biz)

        qs = PMProperty.objects.filter(business=biz)

        # -----------------------------
        # Filters (exact)
        # -----------------------------
        q = (self.request.query_params.get("q") or "").strip()
        city = (self.request.query_params.get("city") or "").strip()
        zip_code = (self.request.query_params.get("zip") or "").strip()
        property_type = (self.request.query_params.get("property_type") or "").strip()
        status = (self.request.query_params.get("status") or "").strip()

        if city:
            qs = qs.filter(city__iexact=city)

        if zip_code:
            qs = qs.filter(zip__iexact=zip_code)

        # choices are usually stored exactly (e.g., "HOME", "HEALTHY") — keep exact match
        if property_type:
            qs = qs.filter(property_type=property_type)

        if status:
            qs = qs.filter(status=status)

        # -----------------------------
        # Fuzzy search (q)
        # -----------------------------
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(address__icontains=q)
                | Q(city__icontains=q)
                | Q(state__icontains=q)
                | Q(zip__icontains=q)
            )

        # -----------------------------
        # Performance: annotate counts
        # -----------------------------
        # NOTE: This assumes PMUnit.property has related_name="units".
        # If your related_name differs, update "units" below accordingly.
        qs = qs.annotate(
            units_count_anno=Count("units", distinct=True),
            occupied_units_anno=Count(
                "units",
                filter=Q(units__status=PMUnit.Status.OCCUPIED),
                distinct=True,
            ),
            section8_units_anno=Count(
                "units",
                filter=Q(units__section8_active=True),
                distinct=True,
            ),
        )

        # -----------------------------
        # Ordering (safe allowlist)
        # -----------------------------
        ordering = (self.request.query_params.get("ordering") or "").strip()
        if ordering:
            desc = ordering.startswith("-")
            field = ordering[1:] if desc else ordering
            if field in self.ALLOWED_ORDER_FIELDS:
                qs = qs.order_by(f"-{field}" if desc else field, "-updated_at", "-id")
            else:
                qs = qs.order_by("-updated_at", "-id")
        else:
            qs = qs.order_by("-updated_at", "-id")

        return qs

    def perform_create(self, serializer):
        biz = get_business_from_header(self.request)
        require_business_access(self.request.user, biz)
        serializer.save(business=biz)
