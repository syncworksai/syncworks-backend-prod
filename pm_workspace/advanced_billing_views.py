from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .billing_views import PROFILE_PACKET_TYPE, _active_lease, _profile_packet, _tenant_account
from .models import PMLedgerEntry, PMTenant, PMWorkspace


ADVANCED_DEFAULTS = {
    "late_fee_rules": [],
    "payment_arrangement_enabled": False,
    "payment_arrangement_frequency": "BIWEEKLY",
    "payment_arrangement_amount": "0.00",
    "payment_arrangement_start": "",
    "payment_arrangement_end": "",
    "pause_late_fees_during_arrangement": True,
    "collection_status": "NONE",
    "collection_start_date": "",
    "collection_monthly_late_fee_cap": "0.00",
    "eviction_filed": False,
    "eviction_filed_date": "",
    "stop_late_fees_after_eviction": False,
    "move_out_date": "",
    "prorate_final_month": False,
    "deposit_required": "0.00",
    "deposit_received": "0.00",
    "deposit_held": "0.00",
    "deposit_applied": "0.00",
    "deposit_notes": "",
    "collections_recipient_name": "",
    "collections_recipient_email": "",
    "collections_notes": "",
}


def _workspace(request):
    workspace_id = request.headers.get("X-PM-Workspace-ID") or request.query_params.get("workspace_id")
    if not workspace_id and isinstance(request.data, dict):
        workspace_id = request.data.get("workspace_id")
    qs = PMWorkspace.objects.filter(owner=request.user, is_active=True)
    workspace = qs.filter(pk=workspace_id).first() if workspace_id else qs.order_by("id").first()
    if not workspace:
        raise PermissionDenied("Create or select a Property Management portfolio first.")
    return workspace


def _tenant(workspace, tenant_id):
    return PMTenant.objects.filter(workspace=workspace, pk=tenant_id).first()


def _money(value, default="0.00"):
    try:
        return Decimal(str(value if value not in (None, "") else default)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default).quantize(Decimal("0.01"))


def _date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _advanced_profile(tenant):
    packet = _profile_packet(tenant, create=True)
    data = dict(ADVANCED_DEFAULTS)
    if isinstance(packet.field_data, dict):
        data.update(packet.field_data)
    data["tenant_id"] = tenant.id
    data["tenant_name"] = f"{tenant.first_name} {tenant.last_name}".strip()
    data["property_name"] = tenant.property_name
    data["unit_label"] = tenant.unit_label
    return data


def _normalize_rules(raw_rules):
    rules = []
    if not isinstance(raw_rules, list):
        return rules
    for index, raw in enumerate(raw_rules[:10]):
        if not isinstance(raw, dict):
            continue
        mode = str(raw.get("mode") or "FIXED_DAY").upper()
        if mode not in {"FIXED_DAY", "DAYS_LATE", "DAILY"}:
            continue
        trigger = max(1, min(int(raw.get("trigger") or 1), 31))
        amount = _money(raw.get("amount"))
        cap = _money(raw.get("monthly_cap"))
        rules.append({
            "id": str(raw.get("id") or f"rule-{index + 1}"),
            "label": str(raw.get("label") or f"Late fee rule {index + 1}").strip(),
            "mode": mode,
            "trigger": trigger,
            "amount": str(amount),
            "monthly_cap": str(cap),
            "enabled": bool(raw.get("enabled", True)),
        })
    return rules


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def advanced_tenant_billing(request, tenant_id):
    workspace = _workspace(request)
    tenant = _tenant(workspace, tenant_id)
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "GET":
        return Response({"profile": _advanced_profile(tenant), "account": _tenant_account(tenant)})

    packet = _profile_packet(tenant, create=True)
    data = dict(packet.field_data or {})
    incoming = request.data or {}
    data.update({
        "late_fee_rules": _normalize_rules(incoming.get("late_fee_rules", data.get("late_fee_rules", []))),
        "payment_arrangement_enabled": bool(incoming.get("payment_arrangement_enabled", data.get("payment_arrangement_enabled", False))),
        "payment_arrangement_frequency": str(incoming.get("payment_arrangement_frequency", data.get("payment_arrangement_frequency", "BIWEEKLY"))).upper(),
        "payment_arrangement_amount": str(_money(incoming.get("payment_arrangement_amount", data.get("payment_arrangement_amount")))),
        "payment_arrangement_start": str(incoming.get("payment_arrangement_start", data.get("payment_arrangement_start", "")) or ""),
        "payment_arrangement_end": str(incoming.get("payment_arrangement_end", data.get("payment_arrangement_end", "")) or ""),
        "pause_late_fees_during_arrangement": bool(incoming.get("pause_late_fees_during_arrangement", data.get("pause_late_fees_during_arrangement", True))),
        "collection_status": str(incoming.get("collection_status", data.get("collection_status", "NONE"))).upper(),
        "collection_start_date": str(incoming.get("collection_start_date", data.get("collection_start_date", "")) or ""),
        "collection_monthly_late_fee_cap": str(_money(incoming.get("collection_monthly_late_fee_cap", data.get("collection_monthly_late_fee_cap")))),
        "eviction_filed": bool(incoming.get("eviction_filed", data.get("eviction_filed", False))),
        "eviction_filed_date": str(incoming.get("eviction_filed_date", data.get("eviction_filed_date", "")) or ""),
        "stop_late_fees_after_eviction": bool(incoming.get("stop_late_fees_after_eviction", data.get("stop_late_fees_after_eviction", False))),
        "move_out_date": str(incoming.get("move_out_date", data.get("move_out_date", "")) or ""),
        "prorate_final_month": bool(incoming.get("prorate_final_month", data.get("prorate_final_month", False))),
        "deposit_required": str(_money(incoming.get("deposit_required", data.get("deposit_required")))),
        "deposit_received": str(_money(incoming.get("deposit_received", data.get("deposit_received")))),
        "deposit_held": str(_money(incoming.get("deposit_held", data.get("deposit_held")))),
        "deposit_applied": str(_money(incoming.get("deposit_applied", data.get("deposit_applied")))),
        "deposit_notes": str(incoming.get("deposit_notes", data.get("deposit_notes", "")) or ""),
        "collections_recipient_name": str(incoming.get("collections_recipient_name", data.get("collections_recipient_name", "")) or ""),
        "collections_recipient_email": str(incoming.get("collections_recipient_email", data.get("collections_recipient_email", "")) or ""),
        "collections_notes": str(incoming.get("collections_notes", data.get("collections_notes", "")) or ""),
    })
    packet.field_data = data
    packet.lease = _active_lease(tenant)
    packet.save(update_fields=["field_data", "lease", "updated_at"])
    return Response({"detail": "Lease-specific billing rules saved.", "profile": _advanced_profile(tenant), "account": _tenant_account(tenant)})


def _signed(entry):
    return entry.amount if entry.entry_type in {PMLedgerEntry.EntryType.CHARGE, PMLedgerEntry.EntryType.ADJUSTMENT} else -entry.amount


def _balance_through(tenant, cutoff):
    return sum((_signed(entry) for entry in tenant.ledger_entries.filter(entry_date__lte=cutoff)), Decimal("0.00"))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def generate_advanced_late_fees(request, tenant_id):
    workspace = _workspace(request)
    tenant = _tenant(workspace, tenant_id)
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)
    profile = _advanced_profile(tenant)
    through = _date(request.data.get("through_date")) or timezone.localdate()
    rules = [rule for rule in profile.get("late_fee_rules", []) if rule.get("enabled")]
    if not rules:
        return Response({"detail": "Add at least one enabled late-fee rule."}, status=status.HTTP_400_BAD_REQUEST)
    start = _date(profile.get("billing_start_date")) or _date(profile.get("lease_start")) or tenant.move_in_date or through
    arrangement_start = _date(profile.get("payment_arrangement_start"))
    arrangement_end = _date(profile.get("payment_arrangement_end"))
    eviction_date = _date(profile.get("eviction_filed_date"))
    collection_start = _date(profile.get("collection_start_date"))
    collection_cap = _money(profile.get("collection_monthly_late_fee_cap"))
    created = []

    cursor = date(start.year, start.month, 1)
    end_month = date(through.year, through.month, 1)
    while cursor <= end_month:
        month_end = date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
        month_through = min(month_end, through)
        due_day = int(profile.get("rent_due_day") or 1)
        due = date(cursor.year, cursor.month, min(due_day, calendar.monthrange(cursor.year, cursor.month)[1]))
        monthly_created = Decimal("0.00")
        existing_monthly = sum((entry.amount for entry in tenant.ledger_entries.filter(category="LATE_FEE", entry_date__year=cursor.year, entry_date__month=cursor.month)), Decimal("0.00"))
        monthly_created += existing_monthly

        for rule in rules:
            mode = rule["mode"]
            trigger = int(rule["trigger"])
            amount = _money(rule["amount"])
            rule_cap = _money(rule.get("monthly_cap"))
            candidate_dates = []
            if mode == "FIXED_DAY":
                candidate_dates = [date(cursor.year, cursor.month, min(trigger, calendar.monthrange(cursor.year, cursor.month)[1]))]
            elif mode == "DAYS_LATE":
                candidate_dates = [due + timedelta(days=trigger)]
            else:
                first = due + timedelta(days=trigger)
                if first <= month_through:
                    candidate_dates = [first + timedelta(days=offset) for offset in range((month_through - first).days + 1)]

            for fee_date in candidate_dates:
                if fee_date < start or fee_date > through:
                    continue
                if profile.get("payment_arrangement_enabled") and profile.get("pause_late_fees_during_arrangement") and arrangement_start and arrangement_end and arrangement_start <= fee_date <= arrangement_end:
                    continue
                if profile.get("stop_late_fees_after_eviction") and eviction_date and fee_date >= eviction_date:
                    continue
                if _balance_through(tenant, fee_date) <= 0:
                    continue
                effective_cap = rule_cap if rule_cap > 0 else Decimal("0.00")
                if collection_start and fee_date >= collection_start and collection_cap > 0:
                    effective_cap = collection_cap if effective_cap <= 0 else min(effective_cap, collection_cap)
                fee = amount
                if effective_cap > 0:
                    fee = min(fee, max(effective_cap - monthly_created, Decimal("0.00")))
                if fee <= 0:
                    continue
                ref = f"AUTO-LATE2-{tenant.id}-{rule['id']}-{fee_date.isoformat()}"
                if tenant.ledger_entries.filter(reference=ref).exists():
                    continue
                entry = PMLedgerEntry.objects.create(
                    workspace=workspace,
                    tenant=tenant,
                    lease=_active_lease(tenant),
                    entry_date=fee_date,
                    entry_type=PMLedgerEntry.EntryType.CHARGE,
                    amount=fee,
                    category="LATE_FEE",
                    reference=ref,
                    memo=f"{rule['label']} for {cursor:%B %Y}",
                    created_by=request.user,
                )
                created.append(entry.id)
                monthly_created += fee
        cursor = date(cursor.year + (1 if cursor.month == 12 else 0), 1 if cursor.month == 12 else cursor.month + 1, 1)

    return Response({"detail": f"Generated {len(created)} advanced late-fee charge(s).", "created_entry_ids": created, "account": _tenant_account(tenant, through)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def collections_statement_preview(request, tenant_id):
    workspace = _workspace(request)
    tenant = _tenant(workspace, tenant_id)
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)
    profile = _advanced_profile(tenant)
    cap = _money(request.data.get("monthly_late_fee_cap", profile.get("collection_monthly_late_fee_cap")))
    move_out = _date(request.data.get("move_out_date", profile.get("move_out_date")))
    prorate = bool(request.data.get("prorate_final_month", profile.get("prorate_final_month", False)))
    entries = list(tenant.ledger_entries.order_by("entry_date", "id"))
    adjusted_rows = []
    late_used = defaultdict(lambda: Decimal("0.00"))
    original_total = sum((_signed(entry) for entry in entries), Decimal("0.00"))

    for entry in entries:
        amount = entry.amount
        adjustment_note = ""
        include = True
        if entry.category == "LATE_FEE" and cap > 0:
            key = (entry.entry_date.year, entry.entry_date.month)
            available = max(cap - late_used[key], Decimal("0.00"))
            adjusted = min(amount, available)
            late_used[key] += adjusted
            if adjusted != amount:
                adjustment_note = f"Late fee reduced from ${amount} to ${adjusted} to honor the monthly collections cap."
            amount = adjusted
            if amount <= 0:
                include = False
        if prorate and move_out and entry.category == "RENT" and entry.entry_type == PMLedgerEntry.EntryType.CHARGE and entry.entry_date.year == move_out.year and entry.entry_date.month == move_out.month:
            days = calendar.monthrange(move_out.year, move_out.month)[1]
            adjusted = (amount * Decimal(move_out.day) / Decimal(days)).quantize(Decimal("0.01"))
            if adjusted != amount:
                adjustment_note = f"Final month prorated through {move_out.isoformat()} from ${amount} to ${adjusted}."
            amount = adjusted
        if include:
            signed = amount if entry.entry_type in {PMLedgerEntry.EntryType.CHARGE, PMLedgerEntry.EntryType.ADJUSTMENT} else -amount
            adjusted_rows.append({
                "id": entry.id,
                "entry_date": entry.entry_date,
                "entry_type": entry.entry_type,
                "category": entry.category,
                "amount": str(amount),
                "signed_amount": str(signed),
                "payment_method": entry.payment_method,
                "reference": entry.reference,
                "memo": entry.memo,
                "adjustment_note": adjustment_note,
            })
    adjusted_total = sum((Decimal(row["signed_amount"]) for row in adjusted_rows), Decimal("0.00"))
    return Response({
        "tenant": {
            "id": tenant.id,
            "name": f"{tenant.first_name} {tenant.last_name}".strip(),
            "email": tenant.email,
            "property_name": tenant.property_name,
            "unit_label": tenant.unit_label,
        },
        "statement_date": timezone.localdate(),
        "monthly_late_fee_cap": str(cap),
        "move_out_date": move_out,
        "prorate_final_month": prorate,
        "original_balance": str(original_total.quantize(Decimal("0.01"))),
        "adjusted_balance": str(adjusted_total.quantize(Decimal("0.01"))),
        "rows": adjusted_rows,
        "recipient_name": profile.get("collections_recipient_name", ""),
        "recipient_email": profile.get("collections_recipient_email", ""),
        "notes": profile.get("collections_notes", ""),
    })
