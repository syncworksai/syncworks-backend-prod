# backend/user_accounts/viewsets/pm_billing_settings.py
from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models.business import Business
from user_accounts.models.pm_billing_settings import PMBillingSettings
from user_accounts.serializers.pm_billing_settings import PMBillingSettingsSerializer


def _get_business_from_header(request) -> Business:
    raw = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
    if not raw:
        raise ValidationError({"detail": "Missing X-Business-Id header."})
    try:
        bid = int(raw)
    except Exception:
        raise ValidationError({"detail": "Invalid X-Business-Id header."})

    from user_accounts.models.business import Business  # local import to avoid cycles
    try:
        return Business.objects.get(id=bid)
    except Business.DoesNotExist:
        raise ValidationError({"detail": "Business not found."})


def _require_business_access(user, business: Business) -> None:
    from user_accounts.models.business import BusinessMember

    if business.owner_id == user.id:
        return
    if BusinessMember.objects.filter(business=business, user=user, is_active=True).exists():
        return
    raise PermissionDenied("You do not have access to this business.")


class PMBillingSettingsViewSet(viewsets.ModelViewSet):
    """
    PM-side settings per business.
    Use `GET /pm/billing-settings/me/` to fetch-or-create the single settings row.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PMBillingSettingsSerializer

    def get_queryset(self):
        biz = _get_business_from_header(self.request)
        _require_business_access(self.request.user, biz)
        return PMBillingSettings.objects.filter(business_id=biz.id)

    @action(detail=False, methods=["GET"], url_path="me")
    def me(self, request):
        biz = _get_business_from_header(request)
        _require_business_access(request.user, biz)

        obj, _created = PMBillingSettings.objects.get_or_create(business_id=biz.id)
        return Response(PMBillingSettingsSerializer(obj).data, status=status.HTTP_200_OK)

    def perform_create(self, serializer):
        biz = _get_business_from_header(self.request)
        _require_business_access(self.request.user, biz)
        serializer.save(business_id=biz.id)
