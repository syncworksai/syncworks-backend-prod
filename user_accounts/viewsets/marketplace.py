from __future__ import annotations

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import Business, ServiceCategory
from user_accounts.serializers import (
    ServiceCategorySerializer,
    ServiceRequestCreateSerializer,
    ServiceRequestSerializer,
)
from user_accounts.services.tickets import create_request_and_ticket


def _coerce_bool(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in ("1", "true", "t", "yes", "y", "on")


class ServiceCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ServiceCategorySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ServiceCategory.objects.filter(is_active=True).order_by("sort_order", "name")

        parent_id = self.request.query_params.get("parent")
        search = (self.request.query_params.get("search") or self.request.query_params.get("q") or "").strip()
        only_leaves = self.request.query_params.get("leaves")

        if parent_id not in (None, "", "null"):
            try:
                qs = qs.filter(parent_id=int(parent_id))
            except Exception:
                qs = qs.none()

        if search:
            qs = qs.filter(name__icontains=search)

        if _coerce_bool(only_leaves):
            qs = [c for c in qs if not c.children.filter(is_active=True).exists()]

        return qs


class ServiceRequestViewSet(viewsets.ModelViewSet):
    serializer_class = ServiceRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.request.user.service_requests.all().order_by("-created_at")

    def create(self, request, *args, **kwargs):
        ser = ServiceRequestCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        category_id = ser.validated_data["category"]
        category = ServiceCategory.objects.get(id=category_id)

        # Normalize location fields: accept either service_* or address/zip_code
        raw_zip = (
            ser.validated_data.get("service_zip", None)
            or request.data.get("service_zip", None)
            or request.data.get("zip_code", None)
            or ""
        )
        raw_addr = (
            ser.validated_data.get("service_address", None)
            or request.data.get("service_address", None)
            or request.data.get("address", None)
            or ""
        )

        raw_radius = (
            ser.validated_data.get("service_radius_miles", None)
            if "service_radius_miles" in ser.validated_data
            else request.data.get("service_radius_miles", None)
        )
        try:
            raw_radius = int(raw_radius) if raw_radius not in (None, "", "null") else None
        except Exception:
            raw_radius = None

        raw_is_marketplace = ser.validated_data.get("is_marketplace", None)
        if raw_is_marketplace is None:
            raw_is_marketplace = request.data.get("is_marketplace", False)
        raw_is_marketplace = _coerce_bool(raw_is_marketplace)

        # Direct routing: accept business_id or target_business from validated data
        target_business_id = ser.validated_data.get("target_business", None)
        if target_business_id is None:
            target_business_id = request.data.get("target_business", None) or request.data.get("business_id", None)
        try:
            target_business_id = int(target_business_id) if target_business_id not in (None, "", "null") else None
        except Exception:
            target_business_id = None

        target_business = None
        if target_business_id:
            target_business = Business.objects.filter(id=target_business_id, is_active=True).first()

        # Create base SR + Ticket
        sr = create_request_and_ticket(
            customer=request.user,
            category=category,
            title=ser.validated_data["title"],
            description=ser.validated_data.get("description", ""),
            preferred_sbo_user=ser.validated_data.get("preferred_sbo_user", None),
            service_zip=str(raw_zip or "").strip(),
            service_radius_miles=raw_radius,
            service_address=str(raw_addr or "").strip(),
            is_marketplace=bool(raw_is_marketplace),
        )

        # Apply direct routing after creation
        if target_business:
            sr.target_business = target_business
            sr.save(update_fields=["target_business"])

            try:
                t = sr.ticket
                t.assigned_business = target_business
                t.is_marketplace = False

                if hasattr(t, "assigned_at") and getattr(t, "assigned_at", None) is None:
                    from django.utils import timezone

                    t.assigned_at = timezone.now()

                t.save()
            except Exception:
                pass

        return Response(ServiceRequestSerializer(sr).data, status=201)