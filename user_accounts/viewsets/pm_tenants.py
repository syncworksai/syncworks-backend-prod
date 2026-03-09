from __future__ import annotations

from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from user_accounts.models.business import Business, BusinessMember
from user_accounts.models.pm_tenant import PMTenant
from user_accounts.serializers.pm_tenants import PMTenantSerializer


def _get_business_from_header(request) -> Business:
    raw = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
    if not raw:
        raise ValidationError({"detail": "Missing X-Business-Id header."})
    try:
        bid = int(raw)
    except Exception:
        raise ValidationError({"detail": "Invalid X-Business-Id header."})

    try:
        return Business.objects.get(id=bid)
    except Business.DoesNotExist:
        raise ValidationError({"detail": "Business not found."})


def _require_business_access(user, business: Business) -> None:
    if business.owner_id == user.id:
        return
    if BusinessMember.objects.filter(business=business, user=user, is_active=True).exists():
        return
    raise PermissionDenied("You do not have access to this business.")


class PMTenantViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMTenantSerializer

    def get_queryset(self):
        biz = _get_business_from_header(self.request)
        _require_business_access(self.request.user, biz)
        return PMTenant.objects.filter(business=biz).select_related("property", "unit", "unit__property")

    def perform_create(self, serializer):
        biz = _get_business_from_header(self.request)
        _require_business_access(self.request.user, biz)

        unit = serializer.validated_data.get("unit")
        prop = serializer.validated_data.get("property")

        # Validate unit belongs to biz if provided
        if unit and getattr(unit, "business_id", None) != biz.id:
            raise ValidationError({"unit": "Unit must belong to the active business."})

        # Validate property belongs to biz if provided
        if prop and getattr(prop, "business_id", None) != biz.id:
            raise ValidationError({"property": "Property must belong to the active business."})

        # If both provided, ensure unit is under property
        if unit and prop and unit.property_id != prop.id:
            raise ValidationError({"unit": "Unit must belong to the selected property."})

        serializer.save(business=biz)
