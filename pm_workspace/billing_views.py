from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import PMDocumentPacket, PMLedgerEntry, PMLease, PMTenant, PMWorkspace


PROFILE_PACKET_TYPE = "TENANT_BILLING_PROFILE"
DEFAULT_PROFILE = {
    "rent_due_day": 1,
    "grace_days": 5,
    "late_fee_type": "FLAT",
    "late_fee_amount": "0.00",
    "auto_charge_rent": True,
    "auto_charge_late_fee": False,
    "charge_security_deposit": True,
    "billing_start_date": "",
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


def _tenant_for_workspace(workspace, tenant_id):
    return PMTenant.objects.filter(workspace=workspace, pk=tenant_id).first()


def _active_lease(tenant):
    return tenant.leases.exclude(status="ENDED").order_by("-start_date", "-id").first()


def _profile_packet(tenant, create=False):
    packet = tenant.document_packets.filter(packet_type=PROFILE_PACKET_TYPE).order_by("-updated_at", "-id").first()
    if packet or not create:
        return packet
    lease = _active_lease(tenant)
    return PMDocumentPacket.objects.create(
        workspace=tenant.workspace,
        tenant=tenant,
        lease=lease,
        packet_type=PROFILE_PACKET_TYPE,
        state_code="",
        template_name="Tenant billing profile",
        template_version="1",
        field_data=dict(DEFAULT_PROFILE),
    )


def _profile(tenant):
    packet = _profile_packet(tenant)
    data = dict(DEFAULT_PROFILE)
    if packet and isinstance(packet.field_data, dict):
        data.update(packet.field_data)
    lease = _active_lease(tenant)
    data["tenant_id"] = tenant.id
    data["tenant_name"] = f"{tenant.first_name} {tenant.last_name}".strip()
    data["lease_id"] = lease.id if lease else None
    data["monthly_rent"] = str((lease.monthly_rent if lease else tenant.monthly_rent) or Decimal("0.00"))
    data["security_deposit"] = str((lease.security_deposit if lease else None) or Decimal("0.00"))
    data["section8"] = bool(lease.section8) if lease else False
    data["tenant_portion"] = str((lease.tenant_portion if lease else None) or Decimal("0.00"))
    data["assistance_portion"] = str((lease.assistance_portion if lease else None) or Decimal("0.00"))
    data["lease_start"] = lease.start_date.isoformat() if lease else (tenant.lease_start.isoformat() if tenant.lease_start else "")
    data["lease_end"] = lease.end_date.isoformat() if lease and lease.end_date else (tenant.lease_end.isoformat() if tenant.lease_end else "")
    return data


def _money(value, default="0.00"):
    try:
        return Decimal(str(value if value not in (None, "") else default)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default).quantize(Decimal("0.01"))


def _signed(entry):
    return entry.amount if entry.entry_type in {PMLedgerEntry.EntryType.CHARGE, PMLedgerEntry.EntryType.ADJUSTMENT} else -entry.amount


def _tenant_account(tenant, as_of=None):
    as_of = as_of or timezone.localdate()
    entries = list(tenant.ledger_entries.order_by("entry_date", "id"))
    balance = sum((_signed(entry) for entry in entries), Decimal("0.00"))
    charges_due = sum((_signed(entry) for entry in entries if entry.entry_date <= as_of), Decimal("0.00"))
    future = balance - charges_due
    profile = _profile(tenant)
    due_day = max(1, min(int(profile.get("rent_due_day") or 1), 28))
    current_due_date = date(as_of.year, as_of.month, due_day)
    past_due_cutoff = current_due_date if as_of >= current_due_date else (current_due_date.replace(day=1) - timedelta(days=1))
    past_due = sum((_signed(entry) for entry in entries if entry.entry_date < past_due_cutoff), Decimal("0.00"))
    late_fees = sum((entry.amount for entry in entries if entry.entry_type == PMLedgerEntry.EntryType.CHARGE and entry.category == "LATE_FEE"), Decimal("0.00"))
    deposits = sum((_signed(entry) for entry in entries if entry.category == "SECURITY_DEPOSIT"), Decimal("0.00"))
    last_payment = next((entry for entry in reversed(entries) if entry.entry_type == PMLedgerEntry.EntryType.PAYMENT), None)
    return {
        "tenant_id": tenant.id,
        "tenant_name": f"{tenant.first_name} {tenant.last_name}".strip(),
        "balance": str(balance.quantize(Decimal("0.01"))),
        "amount_due": str(max(charges_due, Decimal("0.00")).quantize(Decimal("0.01"))),
        "past_due": str(max(past_due, Decimal("0.00")).quantize(Decimal("0.01"))),
        "future_charges": str(max(future, Decimal("0.00")).quantize(Decimal("0.01"))),
        "late_fees_charged": str(late_fees.quantize(Decimal("0.01"))),
        "deposit_balance": str(deposits.quantize(Decimal("0.01"))),
        "next_due_date": current_due_date.isoformat() if as_of <= current_due_date else date(as_of.year + (1 if as_of.month == 12 else 0), 1 if as_of.month == 12 else as_of.month + 1, due_day).isoformat(),
        "last_payment_amount": str(last_payment.amount) if last_payment else "0.00",
        "last_payment_date": last_payment.entry_date.isoformat() if last_payment else None,
        "profile": profile,
    }


def _month_starts(start_date, end_date):
    cursor = date(start_date.year, start_date.month, 1)
    end = date(end_date.year, end_date.month, 1)
    while cursor <= end:
        yield cursor
        cursor = date(cursor.year + (1 if cursor.month == 12 else 0), 1 if cursor.month == 12 else cursor.month + 1, 1)


def _due_date(month_start, due_day):
    day = min(due_day, calendar.monthrange(month_start.year, month_start.month)[1])
    return date(month_start.year, month_start.month, day)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def tenant_billing_profile(request, tenant_id):
    workspace = _workspace(request)
    tenant = _tenant_for_workspace(workspace, tenant_id)
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "GET":
        return Response({"profile": _profile(tenant), "account": _tenant_account(tenant)})

    packet = _profile_packet(tenant, create=True)
    data = dict(DEFAULT_PROFILE)
    if isinstance(packet.field_data, dict):
        data.update(packet.field_data)
    incoming = request.data or {}
    due_day = int(incoming.get("rent_due_day", data["rent_due_day"]) or 1)
    grace_days = int(incoming.get("grace_days", data["grace_days"]) or 0)
    if due_day < 1 or due_day > 28:
        return Response({"rent_due_day": "Rent due day must be between 1 and 28."}, status=status.HTTP_400_BAD_REQUEST)
    if grace_days < 0 or grace_days > 30:
        return Response({"grace_days": "Grace period must be between 0 and 30 days."}, status=status.HTTP_400_BAD_REQUEST)
    late_fee_type = str(incoming.get("late_fee_type", data["late_fee_type"]) or "FLAT").upper()
    if late_fee_type not in {"FLAT", "PERCENT"}:
        return Response({"late_fee_type": "Choose FLAT or PERCENT."}, status=status.HTTP_400_BAD_REQUEST)
    data.update({
        "rent_due_day": due_day,
        "grace_days": grace_days,
        "late_fee_type": late_fee_type,
        "late_fee_amount": str(_money(incoming.get("late_fee_amount", data["late_fee_amount"]))),
        "auto_charge_rent": bool(incoming.get("auto_charge_rent", data["auto_charge_rent"])),
        "auto_charge_late_fee": bool(incoming.get("auto_charge_late_fee", data["auto_charge_late_fee"])),
        "charge_security_deposit": bool(incoming.get("charge_security_deposit", data["charge_security_deposit"])),
        "billing_start_date": str(incoming.get("billing_start_date", data.get("billing_start_date", "")) or ""),
    })
    packet.field_data = data
    packet.lease = _active_lease(tenant)
    packet.save(update_fields=["field_data", "lease", "updated_at"])
    return Response({"detail": "Tenant billing rules saved.", "profile": _profile(tenant), "account": _tenant_account(tenant)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def generate_tenant_charges(request, tenant_id):
    workspace = _workspace(request)
    tenant = _tenant_for_workspace(workspace, tenant_id)
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)
    lease = _active_lease(tenant)
    if not lease and not tenant.monthly_rent:
        return Response({"detail": "Add a lease or monthly rent before generating charges."}, status=status.HTTP_400_BAD_REQUEST)
    profile = _profile(tenant)
    through_raw = str(request.data.get("through_date") or timezone.localdate().isoformat())
    try:
        through_date = date.fromisoformat(through_raw)
    except ValueError:
        return Response({"through_date": "Enter a valid date."}, status=status.HTTP_400_BAD_REQUEST)
    start_raw = str(profile.get("billing_start_date") or profile.get("lease_start") or tenant.move_in_date or through_date)
    try:
        start_date = date.fromisoformat(start_raw) if isinstance(start_raw, str) else start_raw
    except ValueError:
        start_date = lease.start_date if lease else (tenant.move_in_date or through_date)
    due_day = int(profile.get("rent_due_day") or 1)
    grace_days = int(profile.get("grace_days") or 0)
    monthly_rent = _money(profile.get("tenant_portion")) if profile.get("section8") and _money(profile.get("tenant_portion")) > 0 else _money(profile.get("monthly_rent"))
    created = []

    if profile.get("charge_security_deposit") and _money(profile.get("security_deposit")) > 0:
        ref = f"AUTO-DEPOSIT-{tenant.id}"
        if not tenant.ledger_entries.filter(reference=ref).exists():
            entry = PMLedgerEntry.objects.create(workspace=workspace, tenant=tenant, lease=lease, entry_date=start_date, entry_type=PMLedgerEntry.EntryType.CHARGE, amount=_money(profile["security_deposit"]), category="SECURITY_DEPOSIT", reference=ref, memo="Automatic security deposit charge", created_by=request.user)
            created.append(entry.id)

    if profile.get("auto_charge_rent"):
        for month_start in _month_starts(start_date, through_date):
            due = _due_date(month_start, due_day)
            if due < start_date or due > through_date:
                continue
            ref = f"AUTO-RENT-{tenant.id}-{month_start:%Y-%m}"
            if not tenant.ledger_entries.filter(reference=ref).exists():
                entry = PMLedgerEntry.objects.create(workspace=workspace, tenant=tenant, lease=lease, entry_date=due, entry_type=PMLedgerEntry.EntryType.CHARGE, amount=monthly_rent, category="RENT", reference=ref, memo=f"Automatic rent charge for {month_start:%B %Y}", created_by=request.user)
                created.append(entry.id)

            if profile.get("auto_charge_late_fee") and _money(profile.get("late_fee_amount")) > 0 and through_date > due + timedelta(days=grace_days):
                late_ref = f"AUTO-LATE-{tenant.id}-{month_start:%Y-%m}"
                if tenant.ledger_entries.filter(reference=late_ref).exists():
                    continue
                balance_at_grace = sum((_signed(e) for e in tenant.ledger_entries.filter(entry_date__lte=due + timedelta(days=grace_days))), Decimal("0.00"))
                if balance_at_grace > 0:
                    fee = _money(profile["late_fee_amount"])
                    if profile.get("late_fee_type") == "PERCENT":
                        fee = (monthly_rent * fee / Decimal("100")).quantize(Decimal("0.01"))
                    entry = PMLedgerEntry.objects.create(workspace=workspace, tenant=tenant, lease=lease, entry_date=due + timedelta(days=grace_days + 1), entry_type=PMLedgerEntry.EntryType.CHARGE, amount=fee, category="LATE_FEE", reference=late_ref, memo=f"Automatic late fee for {month_start:%B %Y}", created_by=request.user)
                    created.append(entry.id)

    return Response({"detail": f"Generated {len(created)} new ledger charge(s).", "created_entry_ids": created, "account": _tenant_account(tenant, through_date)})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def portfolio_billing_summary(request):
    workspace = _workspace(request)
    tenants = PMTenant.objects.filter(workspace=workspace).prefetch_related("ledger_entries", "leases", "document_packets")
    rows = [_tenant_account(tenant) for tenant in tenants]
    rows.sort(key=lambda row: Decimal(row["past_due"]), reverse=True)
    total_due = sum((Decimal(row["amount_due"]) for row in rows), Decimal("0.00"))
    total_past_due = sum((Decimal(row["past_due"]) for row in rows), Decimal("0.00"))
    return Response({"total_due": str(total_due.quantize(Decimal("0.01"))), "total_past_due": str(total_past_due.quantize(Decimal("0.01"))), "past_due_accounts": sum(1 for row in rows if Decimal(row["past_due"]) > 0), "tenants": rows})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_tenant_account(request):
    tenant = PMTenant.objects.filter(user=request.user, status=PMTenant.Status.CONNECTED).prefetch_related("ledger_entries", "leases", "document_packets").order_by("-updated_at").first()
    if not tenant:
        return Response({"detail": "No connected tenant account was found."}, status=status.HTTP_404_NOT_FOUND)
    entries = tenant.ledger_entries.order_by("-entry_date", "-id")[:100]
    return Response({
        "account": _tenant_account(tenant),
        "property_name": tenant.property_name,
        "unit_label": tenant.unit_label,
        "lease": {
            "start_date": tenant.lease_start,
            "end_date": tenant.lease_end,
            "monthly_rent": tenant.monthly_rent,
        },
        "ledger": [{"id": e.id, "entry_date": e.entry_date, "entry_type": e.entry_type, "amount": str(e.amount), "category": e.category, "payment_method": e.payment_method, "reference": e.reference, "memo": e.memo} for e in entries],
    })
