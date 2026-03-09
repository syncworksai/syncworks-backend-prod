from __future__ import annotations

from django.utils import timezone
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from user_accounts.models.business import Business, BusinessMember
from user_accounts.models.pm_invite import PMInvite
from user_accounts.serializers.pm_invites import PMInviteSerializer


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


class PMInviteViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMInviteSerializer

    def get_queryset(self):
        biz = _get_business_from_header(self.request)
        _require_business_access(self.request.user, biz)
        return PMInvite.objects.filter(business=biz).select_related("unit", "unit__property", "created_by")

    def perform_create(self, serializer):
        biz = _get_business_from_header(self.request)
        _require_business_access(self.request.user, biz)

        unit = serializer.validated_data.get("unit")
        if unit and getattr(unit, "business_id", None) != biz.id:
            raise ValidationError({"unit": "Unit must belong to the active business."})

        expires_at = serializer.validated_data.get("expires_at")
        if expires_at and expires_at <= timezone.now():
            raise ValidationError({"expires_at": "expires_at must be in the future."})

        serializer.save(business=biz, created_by=self.request.user)
