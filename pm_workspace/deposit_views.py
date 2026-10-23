from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .billing_views import _active_lease, _profile_packet, _workspace
from .models import PMLedgerEntry, PMTenant, PMDocumentPacket


def _money(value, default="0.00"):
    try:
        return Decimal(str(value if value not in (None, "") else default)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default).quantize(Decimal("0.01"))


def _tenant(workspace, tenant_id):
    return PMTenant.objects.filter(workspace=workspace, pk=tenant_id).first()


EVIDENCE_PACKET_TYPE = "TENANT_DEPOSIT_TRANSFER_REVIEW"


def _evidence_snapshot(tenant):
    packet = tenant.document_packets.filter(packet_type=EVIDENCE_PACKET_TYPE).order_by("-id").first()
    if not packet:
        return {"status": "NOT_RECONCILED", "paperwork_amount": None,
                "reported_transfer_amount": None, "difference": None,
                "description": "", "source_note": "", "affects_rent_balance": False}
    fields = packet.field_data or {}
    listed = _money(fields.get("paperwork_amount"))
    transferred = _money(fields.get("reported_transfer_amount"))
    return {"status": "NEEDS_REVIEW", "paperwork_amount": str(listed),
            "reported_transfer_amount": str(transferred),
            "difference": str((listed-transferred).quantize(Decimal("0.01"))),
            "description": str(fields.get("description") or ""),
            "source_note": str(fields.get("source_note") or ""),
            "affects_rent_balance": False,
            "last_reviewed_at": fields.get("last_reviewed_at")}


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def deposit_transfer_review(request, tenant_id):
    """Document contradictory deposit evidence without posting financial entries.

    Original proposed security deposit, former-manager transfer and any later
    authorized rent credit are three distinct concepts.
    """
    workspace = _workspace(request)
    tenant = PMTenant.objects.select_for_update().filter(workspace=workspace, pk=tenant_id).first()
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "GET":
        return Response({"review": _evidence_snapshot(tenant)})
    def valid_amount(value):
        try:
            number = Decimal(str(value)).quantize(Decimal("0.01"))
        except (ValueError, TypeError, InvalidOperation):
            return None
        return number if number.is_finite() and Decimal("0.00") <= number <= Decimal("999999999.99") else None
    paperwork = valid_amount(request.data.get("paperwork_amount"))
    transfer = valid_amount(request.data.get("reported_transfer_amount"))
    source = str(request.data.get("source_note") or "").strip()
    description = str(request.data.get("description") or "").strip()
    if paperwork is None or transfer is None:
        return Response({"detail": "Enter the separate nonnegative paperwork and reported transfer amounts."}, status=400)
    if len(source) < 15:
        return Response({"detail": "Note the documentary source (15 or more characters)."}, status=400)
    if request.data.get("confirmed") is not True:
        return Response({"detail": "Confirm that the note will not apply a rent credit or establish escrow ownership."}, status=400)
    latest = tenant.document_packets.select_for_update().filter(packet_type=EVIDENCE_PACKET_TYPE).order_by("-id").first()
    fields = dict(latest.field_data or {}) if latest else {}
    fields.update({
        "paperwork_amount": str(paperwork),
        "reported_transfer_amount": str(transfer),
        "description": description[:500],
        "source_note": source[:1200],
        "status": "NEEDS_REVIEW",
        "last_reviewed_at": timezone.now().isoformat(),
        "reviewed_by_user_id": request.user.pk,
        "rent_credit_applied": False,
    })
    if latest:
        history = list(fields.get("history") or [])
        history.append({k: fields[k] for k in ("paperwork_amount", "reported_transfer_amount", "source_note", "last_reviewed_at", "reviewed_by_user_id")})
        latest.field_data = {**fields, "history": history[-50:]}
        latest.save(update_fields=["field_data", "updated_at"])
    else:
        PMDocumentPacket.objects.create(
            workspace=workspace, tenant=tenant, lease=_active_lease(tenant),
            packet_type=EVIDENCE_PACKET_TYPE,
            template_name="Deposit paperwork and former-manager transfer reconciliation",
            field_data={**fields, "history": [{k: fields[k] for k in ("paperwork_amount","reported_transfer_amount","source_note","last_reviewed_at","reviewed_by_user_id")}]})
    return Response({"detail": "Deposit discrepancy noted separately; rent ledger unchanged.",
                     "review": _evidence_snapshot(tenant)}, status=200)


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
        "deposit_review": _evidence_snapshot(tenant),
        "deposit_amount_status": "LEGACY_PROFILE_UNVERIFIED",
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
