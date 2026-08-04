from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .billing_views import _tenant_account
from .models import PMLedgerEntry, PMTenant, PMWorkspace
from .serializers import PMLedgerEntrySerializer


def _workspace(request):
    workspace_id = request.headers.get("X-PM-Workspace-ID") or request.query_params.get("workspace_id")
    if not workspace_id and isinstance(request.data, dict):
        workspace_id = request.data.get("workspace_id")
    qs = PMWorkspace.objects.filter(owner=request.user, is_active=True)
    workspace = qs.filter(pk=workspace_id).first() if workspace_id else qs.order_by("id").first()
    if not workspace:
        raise PermissionDenied("Create or select a Property Management portfolio first.")
    return workspace


def _money(value):
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _reverse_type(entry_type):
    if entry_type in {PMLedgerEntry.EntryType.CHARGE, PMLedgerEntry.EntryType.ADJUSTMENT}:
        return PMLedgerEntry.EntryType.CREDIT
    return PMLedgerEntry.EntryType.CHARGE


def _reversal_reference(entry):
    return f"REVERSAL-{entry.id}"


def _create_reversal(entry, *, user, reason, reversal_date=None):
    existing = entry.tenant.ledger_entries.filter(reference=_reversal_reference(entry)).first()
    if existing:
        return existing, False
    reversal = PMLedgerEntry.objects.create(
        workspace=entry.workspace,
        tenant=entry.tenant,
        lease=entry.lease,
        entry_date=reversal_date or timezone.localdate(),
        entry_type=_reverse_type(entry.entry_type),
        amount=entry.amount,
        category=entry.category,
        payment_method="",
        reference=_reversal_reference(entry),
        memo=f"Reversal of ledger entry #{entry.id}: {reason}".strip(),
        created_by=user,
    )
    return reversal, True


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def correct_ledger_entry(request, entry_id):
    workspace = _workspace(request)
    original = PMLedgerEntry.objects.select_for_update().filter(workspace=workspace, pk=entry_id).select_related("tenant", "lease").first()
    if not original:
        return Response({"detail": "Ledger entry not found."}, status=status.HTTP_404_NOT_FOUND)

    reason = str(request.data.get("reason") or "Ledger correction").strip()
    reversal_date_raw = str(request.data.get("correction_date") or timezone.localdate().isoformat())
    try:
        reversal_date = date.fromisoformat(reversal_date_raw)
    except ValueError:
        return Response({"correction_date": "Enter a valid correction date."}, status=status.HTTP_400_BAD_REQUEST)

    reversal, created = _create_reversal(original, user=request.user, reason=reason, reversal_date=reversal_date)
    replacement = None
    replacement_data = request.data.get("replacement")
    if isinstance(replacement_data, dict) and replacement_data.get("amount") not in (None, ""):
        amount = _money(replacement_data.get("amount"))
        if not amount:
            return Response({"replacement.amount": "Amount must be greater than zero."}, status=status.HTTP_400_BAD_REQUEST)
        entry_type = str(replacement_data.get("entry_type") or original.entry_type).upper()
        if entry_type not in PMLedgerEntry.EntryType.values:
            return Response({"replacement.entry_type": "Choose a valid ledger entry type."}, status=status.HTTP_400_BAD_REQUEST)
        replacement = PMLedgerEntry.objects.create(
            workspace=workspace,
            tenant=original.tenant,
            lease=original.lease,
            entry_date=date.fromisoformat(str(replacement_data.get("entry_date") or reversal_date.isoformat())),
            entry_type=entry_type,
            amount=amount,
            category=str(replacement_data.get("category") or original.category).upper(),
            payment_method=str(replacement_data.get("payment_method") or "").upper() if entry_type == PMLedgerEntry.EntryType.PAYMENT else "",
            reference=f"CORRECTION-{original.id}-{timezone.now():%Y%m%d%H%M%S}",
            memo=str(replacement_data.get("memo") or f"Corrected replacement for ledger entry #{original.id}").strip(),
            created_by=request.user,
        )

    return Response({
        "detail": "Ledger correction saved." if created else "This ledger entry was already reversed.",
        "original": PMLedgerEntrySerializer(original).data,
        "reversal": PMLedgerEntrySerializer(reversal).data,
        "replacement": PMLedgerEntrySerializer(replacement).data if replacement else None,
        "account": _tenant_account(original.tenant),
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def undo_generated_charges(request, tenant_id):
    workspace = _workspace(request)
    tenant = PMTenant.objects.filter(workspace=workspace, pk=tenant_id).first()
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)

    from_raw = str(request.data.get("from_date") or "")
    through_raw = str(request.data.get("through_date") or timezone.localdate().isoformat())
    try:
        from_date = date.fromisoformat(from_raw) if from_raw else None
        through_date = date.fromisoformat(through_raw)
    except ValueError:
        return Response({"detail": "Enter valid undo dates."}, status=status.HTTP_400_BAD_REQUEST)

    qs = tenant.ledger_entries.filter(entry_type=PMLedgerEntry.EntryType.CHARGE, reference__startswith="AUTO-")
    if from_date:
        qs = qs.filter(entry_date__gte=from_date)
    qs = qs.filter(entry_date__lte=through_date).order_by("entry_date", "id")

    reason = str(request.data.get("reason") or "Undo automatic charges generated from the wrong billing start date").strip()
    reversed_ids = []
    skipped_ids = []
    for entry in qs:
        _, created = _create_reversal(entry, user=request.user, reason=reason)
        (reversed_ids if created else skipped_ids).append(entry.id)

    return Response({
        "detail": f"Reversed {len(reversed_ids)} generated charge(s).",
        "reversed_entry_ids": reversed_ids,
        "already_reversed_entry_ids": skipped_ids,
        "account": _tenant_account(tenant),
    })
