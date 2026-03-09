# backend/user_accounts/viewsets/platform_locking.py
from __future__ import annotations

from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from user_accounts.models.business import Business
from user_accounts.models.business_access import BusinessAccessControl
from user_accounts.serializers.business_access import BusinessAccessControlSerializer

# ✅ FIX: permissions is a module file (permissions.py), not a package
from user_accounts.permissions import IsGodMode


class PlatformLockingViewSet(viewsets.ModelViewSet):
    """
    God Mode: Manage lock/unlock state per business (BusinessAccessControl).
    """
    permission_classes = [permissions.IsAuthenticated, IsGodMode]
    serializer_class = BusinessAccessControlSerializer

    def get_queryset(self):
        qs = BusinessAccessControl.objects.select_related("business", "locked_by").order_by("-updated_at")
        locked = self.request.query_params.get("locked")
        if locked in ("1", "true", "yes"):
            qs = qs.filter(is_locked=True)
        if locked in ("0", "false", "no"):
            qs = qs.filter(is_locked=False)

        reason = (self.request.query_params.get("reason") or "").strip()
        if reason:
            qs = qs.filter(lock_reason=reason)
        return qs

    @action(detail=False, methods=["post"])
    def ensure(self, request):
        created = 0
        for b in Business.objects.all().only("id"):
            _, was_created = BusinessAccessControl.objects.get_or_create(business_id=b.id)
            if was_created:
                created += 1
        return Response({"detail": "Ensured access rows.", "created": created})

    @action(detail=True, methods=["post"])
    def lock(self, request, pk=None):
        obj: BusinessAccessControl = self.get_object()
        reason = (request.data.get("reason") or BusinessAccessControl.LockReason.MANUAL).strip() or BusinessAccessControl.LockReason.MANUAL
        obj.lock(reason=reason, actor=request.user)
        return Response({"detail": "Business locked.", "business_id": obj.business_id, "reason": obj.lock_reason})

    @action(detail=True, methods=["post"])
    def unlock(self, request, pk=None):
        obj: BusinessAccessControl = self.get_object()
        obj.unlock(actor=request.user)
        return Response({"detail": "Business unlocked.", "business_id": obj.business_id})

    @action(detail=True, methods=["post"])
    def mark_unlock_requested(self, request, pk=None):
        obj: BusinessAccessControl = self.get_object()
        obj.last_unlock_requested_at = timezone.now()
        obj.save(update_fields=["last_unlock_requested_at", "updated_at"])
        return Response({"detail": "Marked unlock requested.", "business_id": obj.business_id})