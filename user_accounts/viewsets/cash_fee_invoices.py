from __future__ import annotations

from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from user_accounts.models import Business, BusinessMember, CashFeeInvoice
from user_accounts.serializers.cash_fee_invoice import CashFeeInvoiceSerializer
from user_accounts.services.cash_fee_billing import generate_monthly_cash_fee_invoices
from user_accounts.services.cash_fee_collection import (
    charge_cash_fee_invoice,
    collect_open_cash_fee_invoices,
)


def _is_platform_admin(user) -> bool:
    # Safe + simple: treat staff/superuser as God Mode
    try:
        if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
            return True
    except Exception:
        pass

    for attr in ("is_platform_admin", "is_god_mode", "is_admin"):
        try:
            if bool(getattr(user, attr, False)):
                return True
        except Exception:
            continue

    return False


def _user_business_ids(user) -> list[int]:
    ids: set[int] = set()

    try:
        ids.update(list(Business.objects.filter(owner_user=user).values_list("id", flat=True)))
    except Exception:
        pass
    try:
        ids.update(list(Business.objects.filter(owner=user).values_list("id", flat=True)))
    except Exception:
        pass
    try:
        ids.update(list(Business.objects.filter(created_by=user).values_list("id", flat=True)))
    except Exception:
        pass

    try:
        ids.update(list(BusinessMember.objects.filter(user=user, is_active=True).values_list("business_id", flat=True)))
    except Exception:
        pass

    return sorted([int(x) for x in ids if x])


class IsAuthenticatedAndScoped(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        u = getattr(request, "user", None)
        return bool(u and u.is_authenticated)

    def has_object_permission(self, request, view, obj) -> bool:
        u = request.user
        if _is_platform_admin(u):
            return True
        try:
            return int(obj.business_id) in set(_user_business_ids(u))
        except Exception:
            return False


class CashFeeInvoiceViewSet(viewsets.ModelViewSet):
    """
    /api/v1/cash-fee-invoices/

    - Business users: list/retrieve ONLY their own businesses
    - Platform admins: list/retrieve ALL + admin actions + generate + collect
    """

    serializer_class = CashFeeInvoiceSerializer
    permission_classes = [IsAuthenticatedAndScoped]

    queryset = CashFeeInvoice.objects.select_related("business").all().order_by("-created_at")
    http_method_names = ["get", "head", "options", "patch", "post"]

    def get_queryset(self):
        qs = super().get_queryset()
        u = self.request.user
        if _is_platform_admin(u):
            bid = self.request.query_params.get("business_id")
            if bid:
                try:
                    qs = qs.filter(business_id=int(bid))
                except Exception:
                    pass
            return qs

        biz_ids = _user_business_ids(u)
        if not biz_ids:
            return qs.none()
        return qs.filter(business_id__in=biz_ids)

    def create(self, request, *args, **kwargs):
        return Response({"detail": "Direct create disabled."}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        if not _is_platform_admin(request.user):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
        return super().partial_update(request, *args, **kwargs)

    # -------------------------
    # ✅ Platform Admin Actions
    # -------------------------

    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request, pk=None):
        if not _is_platform_admin(request.user):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

        inv: CashFeeInvoice = self.get_object()
        if inv.status == CashFeeInvoice.Status.PAID:
            return Response({"detail": "Already PAID."}, status=status.HTTP_200_OK)

        inv.status = CashFeeInvoice.Status.PAID
        inv.paid_at = timezone.now()
        inv.save(update_fields=["status", "paid_at", "updated_at"])
        return Response(self.get_serializer(inv).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="void")
    def void(self, request, pk=None):
        if not _is_platform_admin(request.user):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

        inv: CashFeeInvoice = self.get_object()
        inv.status = CashFeeInvoice.Status.VOID
        inv.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(inv).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="reopen")
    def reopen(self, request, pk=None):
        if not _is_platform_admin(request.user):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

        inv: CashFeeInvoice = self.get_object()
        inv.status = CashFeeInvoice.Status.OPEN
        inv.paid_at = None
        inv.save(update_fields=["status", "paid_at", "updated_at"])
        return Response(self.get_serializer(inv).data, status=status.HTTP_200_OK)

    # -------------------------
    # ✅ Generator (previous month)
    # -------------------------

    @action(detail=False, methods=["post"], url_path="generate-previous-month")
    def generate_previous_month(self, request):
        if not _is_platform_admin(request.user):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

        fee_bps = request.data.get("fee_bps", 100)
        due_days = request.data.get("due_days", 7)

        try:
            fee_bps = int(fee_bps)
        except Exception:
            fee_bps = 100
        try:
            due_days = int(due_days)
        except Exception:
            due_days = 7

        res = generate_monthly_cash_fee_invoices(fee_bps=fee_bps, due_days=due_days)
        return Response(
            {
                "businesses_considered": res.businesses_considered,
                "businesses_skipped_exempt": res.businesses_skipped_exempt,
                "invoices_created": res.invoices_created,
                "invoices_skipped_zero": res.invoices_skipped_zero,
                "invoices_skipped_existing": res.invoices_skipped_existing,
            },
            status=status.HTTP_200_OK,
        )

    # -------------------------
    # ✅ Collector (autopay)
    # -------------------------

    @action(detail=False, methods=["post"], url_path="collect-open")
    def collect_open(self, request):
        """
        POST /cash-fee-invoices/collect-open/
        Platform admin only.
        Charges OPEN invoices (due_only default true).
        """
        if not _is_platform_admin(request.user):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

        due_only = request.data.get("due_only", True)
        due_only = bool(due_only)

        res = collect_open_cash_fee_invoices(due_only=due_only)
        return Response(
            {
                "considered": res.considered,
                "charged": res.charged,
                "skipped_no_card": res.skipped_no_card,
                "skipped_zero": res.skipped_zero,
                "failed": res.failed,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"], url_path="collect")
    def collect_one(self, request, pk=None):
        """
        POST /cash-fee-invoices/{id}/collect/
        Platform admin only. Charges a single invoice.
        """
        if not _is_platform_admin(request.user):
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

        inv: CashFeeInvoice = self.get_object()
        ok, msg = charge_cash_fee_invoice(inv=inv)
        payload = {"ok": bool(ok), "message": msg, "invoice": self.get_serializer(inv).data}
        return Response(payload, status=status.HTTP_200_OK if ok else status.HTTP_400_BAD_REQUEST)