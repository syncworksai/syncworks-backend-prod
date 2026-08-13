from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .billing_views import _active_lease, _profile_packet, _workspace
from .models import PMLedgerEntry, PMTenant


def _money(value, default="0.00"):
    try:
        return Decimal(str(value if value not in (None, "") else default)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default).quantize(Decimal("0.01"))


def _tenant(workspace, tenant_id):
    return PMTenant.objects.filter(workspace=workspace, pk=tenant_id).first()


def _snapshot(tenant):
    packet = _profile_packet(tenant, create=True)
    data = dict(packet.field_data or {})
    required = _money(data.get("deposit_required"))
    received = _money(data.get("deposit_received"))
    held = _money(data.get("deposit_held"))
    applied = _money(data.get("deposit_applied"))
    return {
        "deposit_required": str(required),
        "deposit_received": str(received),
        "deposit_held": str(held),
        "deposit_applied": str(applied),
        "deposit_remaining": str(max(held, Decimal("0.00"))),
        "deposit_applied_to_payments": applied > 0,
        "deposit_notes": str(data.get("deposit_notes") or ""),
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def deposit_status(request, tenant_id):
    workspace = _workspace(request)
    tenant = _tenant(workspace, tenant_id)
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(_snapshot(tenant))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def apply_deposit(request, tenant_id):
    workspace = _workspace(request)
    tenant = _tenant(workspace, tenant_id)
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)

    amount = _money(request.data.get("amount"))
    if amount <= 0:
        return Response({"amount": "Enter an amount greater than zero."}, status=status.HTTP_400_BAD_REQUEST)

    packet = _profile_packet(tenant, create=True)
    data = dict(packet.field_data or {})
    held = _money(data.get("deposit_held"))
    applied = _money(data.get("deposit_applied"))
    if amount > held:
        return Response({"amount": f"Only ${held} of the deposit is currently held."}, status=status.HTTP_400_BAD_REQUEST)

    applied_to = str(request.data.get("applied_to") or "BALANCE").upper()
    memo = str(request.data.get("memo") or "").strip()
    entry_date = request.data.get("entry_date") or timezone.localdate().isoformat()

    entry = PMLedgerEntry.objects.create(
        workspace=workspace,
        tenant=tenant,
        lease=_active_lease(tenant),
        entry_date=entry_date,
        entry_type=PMLedgerEntry.EntryType.CREDIT,
        amount=amount,
        category="DEPOSIT_APPLIED",
        payment_method="",
        reference=f"DEPOSIT-APPLIED-{tenant.id}-{timezone.now().strftime('%Y%m%d%H%M%S%f')}",
        memo=memo or f"Security deposit applied to {applied_to.replace('_', ' ').title()}",
        created_by=request.user,
    )

    data["deposit_applied"] = str((applied + amount).quantize(Decimal("0.01")))
    data["deposit_held"] = str((held - amount).quantize(Decimal("0.01")))
    data["deposit_notes"] = memo or data.get("deposit_notes", "")
    packet.field_data = data
    packet.lease = _active_lease(tenant)
    packet.save(update_fields=["field_data", "lease", "updated_at"])

    return Response({
        "detail": "Deposit application recorded as a ledger credit.",
        "ledger_entry_id": entry.id,
        "deposit": _snapshot(tenant),
    })
