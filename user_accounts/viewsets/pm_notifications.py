# backend/user_accounts/viewsets/pm_notifications.py
from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from user_accounts.models import Business, BusinessMember, PMInvestor, PMNotification
from user_accounts.serializers.pm_investor import PMNotificationSerializer


def _biz_id_from_request(request) -> int | None:
    raw = request.headers.get("X-Business-Id") or request.META.get("HTTP_X_BUSINESS_ID")
    try:
        return int(raw) if raw else None
    except Exception:
        return None


def _require_biz_id(request) -> int:
    biz_id = _biz_id_from_request(request)
    if not biz_id:
        raise ValidationError({"detail": "X-Business-Id header is required."})
    return biz_id


def _is_platform_admin(user) -> bool:
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False))


def _role_is(user, *roles: str) -> bool:
    r = (getattr(user, "role", "") or "").upper()
    return r in {x.upper() for x in roles}


def _ensure_business_access(request, business_id: int):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        raise PermissionDenied("Authentication required.")

    if _is_platform_admin(user):
        return

    biz = Business.objects.filter(id=business_id, is_active=True).first()
    if not biz:
        raise PermissionDenied("You do not have access to this business.")

    # SBO owner can access
    if _role_is(user, "SBO") and getattr(biz, "owner_id", None) == getattr(user, "id", None):
        return

    # PM/Employees via membership
    is_member = BusinessMember.objects.filter(user_id=user.id, business_id=business_id, is_active=True).exists()
    if is_member:
        return

    # Investor portal access
    if PMInvestor.objects.filter(business_id=business_id, user_id=user.id, is_active=True).exists():
        return

    raise PermissionDenied("You are not a member of this business.")


class PMNotificationViewSet(ModelViewSet):
    """
    router.register(r"pm/notifications", PMNotificationViewSet, basename="pm-notifications")

    Investor portal:
      GET /api/v1/pm/notifications/?unread=1

    Mark read:
      POST /api/v1/pm/notifications/{id}/read/

    Bulk mark read:
      POST /api/v1/pm/notifications/read_all/
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PMNotificationSerializer

    def get_queryset(self):
        biz_id = _require_biz_id(self.request)
        _ensure_business_access(self.request, biz_id)

        qs = PMNotification.objects.filter(business_id=biz_id).order_by("-created_at", "-id")

        unread = self.request.query_params.get("unread")
        if unread in ("1", "true", "True"):
            qs = qs.filter(read_at__isnull=True)

        # Investor portal users only see their notifications
        inv = PMInvestor.objects.filter(business_id=biz_id, user_id=self.request.user.id, is_active=True).first()
        if inv:
            qs = qs.filter(investor_id=inv.id)

        # Optional filter by investor id (god mode)
        investor_id = self.request.query_params.get("investor")
        if investor_id and _is_platform_admin(self.request.user):
            try:
                investor_id = int(investor_id)
            except Exception:
                investor_id = None
            if investor_id:
                qs = qs.filter(investor_id=investor_id)

        return qs

    def perform_create(self, serializer):
        """
        Allow PM operator / owner / admin to create notifications.
        Investors should not create notifications.
        """
        biz_id = _require_biz_id(self.request)
        _ensure_business_access(self.request, biz_id)

        inv = PMInvestor.objects.filter(business_id=biz_id, user_id=self.request.user.id, is_active=True).first()
        if inv and not _is_platform_admin(self.request.user):
            raise PermissionDenied("Investors cannot create notifications.")

        serializer.save(business_id=biz_id)

    @action(detail=True, methods=["post"], url_path="read")
    def read(self, request, pk=None):
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)

        obj: PMNotification = self.get_object()
        if obj.business_id != biz_id:
            raise PermissionDenied("Notification not in this business.")

        # Investors can only mark their own notifications read
        inv = PMInvestor.objects.filter(business_id=biz_id, user_id=request.user.id, is_active=True).first()
        if inv and obj.investor_id != inv.id and not _is_platform_admin(request.user):
            raise PermissionDenied("You do not have access to this notification.")

        if obj.read_at is None:
            obj.read_at = timezone.now()
            obj.save(update_fields=["read_at"])

        return Response({"ok": True, "id": obj.id, "read_at": obj.read_at.isoformat() if obj.read_at else None})

    @action(detail=False, methods=["post"], url_path="read_all")
    def read_all(self, request):
        biz_id = _require_biz_id(request)
        _ensure_business_access(request, biz_id)

        qs = PMNotification.objects.filter(business_id=biz_id, read_at__isnull=True)

        inv = PMInvestor.objects.filter(business_id=biz_id, user_id=request.user.id, is_active=True).first()
        if inv:
            qs = qs.filter(investor_id=inv.id)

        now = timezone.now()
        updated = qs.update(read_at=now)

        return Response({"ok": True, "updated": int(updated), "read_at": now.isoformat()}, status=status.HTTP_200_OK)
