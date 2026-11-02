# backend/user_accounts/viewsets/platform_locking.py
from __future__ import annotations

from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from user_accounts.models.business import Business
from user_accounts.models.cash_fee_invoice import CashFeeInvoice
from user_accounts.models.platform_billing import PlatformBillingProfile
from user_accounts.services.cash_fee_policy import cash_lock_date, should_lock_cash_fees
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

    @action(detail=False, methods=["get"], url_path="cash-status")
    def cash_status(self, request):
        """Founder-only actual cash-fee aging and lock status by business."""
        today = timezone.localdate()
        unpaid = CashFeeInvoice.objects.filter(
            status__in=(CashFeeInvoice.Status.OPEN, CashFeeInvoice.Status.OVERDUE),
        ).select_related("business", "business__owner")
        by_business = {}
        for invoice in unpaid.iterator():
            item = by_business.setdefault(invoice.business_id, {
                "business_id": invoice.business_id,
                "business_name": invoice.business.name,
                "owner_email": getattr(invoice.business.owner, "email", ""),
                "unpaid_cents": 0, "oldest_due": None, "invoice_count": 0,
            })
            item["unpaid_cents"] += int(invoice.amount_cents or 0)
            item["invoice_count"] += 1
            if invoice.due_date and (item["oldest_due"] is None or invoice.due_date < item["oldest_due"]):
                item["oldest_due"] = invoice.due_date
        profiles = {
            p.business_id: p for p in PlatformBillingProfile.objects.filter(
                business_id__in=by_business.keys()
            )
        }
        rows = []
        for item in by_business.values():
            prof = profiles.get(item["business_id"])
            oldest = item["oldest_due"]
            item["lock_at"] = cash_lock_date(oldest).isoformat() if oldest else None
            item["days_until_lock"] = (cash_lock_date(oldest) - today).days if oldest else None
            item["lock_due"] = should_lock_cash_fees(oldest, today)
            item["is_locked"] = bool(prof and prof.is_locked)
            item["lock_reason"] = (prof.lock_reason if prof else "")
            item["oldest_due"] = oldest.isoformat() if oldest else None
            rows.append(item)
        rows.sort(key=lambda row: (row["days_until_lock"] is None, row["days_until_lock"] or 0))
        return Response({"count": len(rows), "results": rows[:500], "truncated": len(rows) > 500})

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