from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .billing_views import _active_lease, _profile_packet, _tenant_account, _workspace
from .models import PMLedgerEntry, PMTenant

PAYER_DEFAULTS = {"payer_split_enabled": False, "installment_schedule_enabled": False, "installment_frequency": "BIWEEKLY", "installment_anchor_date": "", "installment_amount": "0.00", "installment_grace_days": 0, "installment_late_fee_amount": "50.00"}

def _money(value, default="0.00"):
    try: return Decimal(str(value if value not in (None, "") else default)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError): return Decimal(default).quantize(Decimal("0.01"))

def _date(value):
    if not value: return None
    try: return date.fromisoformat(str(value))
    except ValueError: return None

def _tenant(workspace, tenant_id): return PMTenant.objects.filter(workspace=workspace, pk=tenant_id).first()

def _profile(tenant):
    packet = _profile_packet(tenant, create=True)
    data = dict(PAYER_DEFAULTS)
    if isinstance(packet.field_data, dict): data.update(packet.field_data)
    lease = _active_lease(tenant)
    contract = (lease.monthly_rent if lease else tenant.monthly_rent) or Decimal("0.00")
    data.update({"tenant_id": tenant.id,"tenant_name": f"{tenant.first_name} {tenant.last_name}".strip(),"section8": bool(lease.section8) if lease else False,"contract_rent": str(contract),"tenant_portion": str((lease.tenant_portion if lease else None) or Decimal("0.00")),"housing_portion": str((lease.assistance_portion if lease else None) or Decimal("0.00")),"housing_authority": lease.housing_authority if lease else ""})
    return data

def _signed(entry): return entry.amount if entry.entry_type in {PMLedgerEntry.EntryType.CHARGE, PMLedgerEntry.EntryType.ADJUSTMENT} else -entry.amount

def _bucket(entry):
    if str(entry.category or "").upper() == "RENT_HOUSING" or entry.payment_method == PMLedgerEntry.Method.HOUSING_AUTHORITY: return "HOUSING"
    return "TENANT"

def _bucket_summary(tenant):
    tenant_balance = Decimal("0.00"); housing_balance = Decimal("0.00")
    for entry in tenant.ledger_entries.all():
        if _bucket(entry) == "HOUSING": housing_balance += _signed(entry)
        else: tenant_balance += _signed(entry)
    return {"tenant_owes": str(max(tenant_balance, Decimal("0.00")).quantize(Decimal("0.01"))),"housing_owes": str(max(housing_balance, Decimal("0.00")).quantize(Decimal("0.01"))),"tenant_balance": str(tenant_balance.quantize(Decimal("0.01"))),"housing_balance": str(housing_balance.quantize(Decimal("0.01"))),"total_balance": str((tenant_balance + housing_balance).quantize(Decimal("0.01")))}

@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def payer_profile(request, tenant_id):
    workspace = _workspace(request); tenant = _tenant(workspace, tenant_id)
    if not tenant: return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "GET": return Response({"profile": _profile(tenant), "buckets": _bucket_summary(tenant), "account": _tenant_account(tenant)})
    packet = _profile_packet(tenant, create=True); data = dict(packet.field_data or {}); incoming = request.data or {}
    frequency = str(incoming.get("installment_frequency", data.get("installment_frequency", "BIWEEKLY"))).upper()
    if frequency not in {"WEEKLY", "BIWEEKLY"}: return Response({"installment_frequency": "Choose WEEKLY or BIWEEKLY."}, status=status.HTTP_400_BAD_REQUEST)
    data.update({"payer_split_enabled": bool(incoming.get("payer_split_enabled", data.get("payer_split_enabled", False))),"installment_schedule_enabled": bool(incoming.get("installment_schedule_enabled", data.get("installment_schedule_enabled", False))),"installment_frequency": frequency,"installment_anchor_date": str(incoming.get("installment_anchor_date", data.get("installment_anchor_date", "")) or ""),"installment_amount": str(_money(incoming.get("installment_amount", data.get("installment_amount", "0.00")))),"installment_grace_days": max(0, min(int(incoming.get("installment_grace_days", data.get("installment_grace_days", 0)) or 0), 30)),"installment_late_fee_amount": str(_money(incoming.get("installment_late_fee_amount", data.get("installment_late_fee_amount", "50.00"))))})
    packet.field_data = data; packet.lease = _active_lease(tenant); packet.save(update_fields=["field_data", "lease", "updated_at"])
    return Response({"detail": "Section 8 payer and installment schedule saved.", "profile": _profile(tenant), "buckets": _bucket_summary(tenant)})

@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def rebuild_split_rent(request, tenant_id):
    workspace = _workspace(request); tenant = _tenant(workspace, tenant_id)
    if not tenant: return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)
    lease = _active_lease(tenant)
    if not lease or not lease.section8: return Response({"detail": "An active Section 8 lease is required."}, status=status.HTTP_400_BAD_REQUEST)
    tenant_portion = _money(lease.tenant_portion); housing_portion = _money(lease.assistance_portion); contract = _money(lease.monthly_rent)
    if tenant_portion + housing_portion != contract: return Response({"detail": f"Tenant plus housing portions must equal contract rent (${contract})."}, status=status.HTTP_400_BAD_REQUEST)
    start = _date(request.data.get("start_date")) or lease.start_date; through = _date(request.data.get("through_date")) or timezone.localdate(); due_day = max(1, min(int(_profile(tenant).get("rent_due_day") or 1), 28))
    generated = tenant.ledger_entries.filter(entry_date__gte=start, entry_date__lte=through, category__in=["RENT", "RENT_TENANT", "RENT_HOUSING"], reference__startswith="AUTO-"); removed = generated.count(); generated.delete(); created=[]
    cursor = date(start.year, start.month, 1); end = date(through.year, through.month, 1)
    while cursor <= end:
        due = date(cursor.year, cursor.month, due_day)
        if start <= due <= through:
            if tenant_portion > 0: created.append(PMLedgerEntry.objects.create(workspace=workspace, tenant=tenant, lease=lease, entry_date=due, entry_type=PMLedgerEntry.EntryType.CHARGE, amount=tenant_portion, category="RENT_TENANT", reference=f"AUTO-SPLIT-RENT-T-{tenant.id}-{cursor:%Y-%m}", memo=f"Tenant rent portion for {cursor:%B %Y}", created_by=request.user).id)
            if housing_portion > 0: created.append(PMLedgerEntry.objects.create(workspace=workspace, tenant=tenant, lease=lease, entry_date=due, entry_type=PMLedgerEntry.EntryType.CHARGE, amount=housing_portion, category="RENT_HOUSING", reference=f"AUTO-SPLIT-RENT-H-{tenant.id}-{cursor:%Y-%m}", memo=f"Housing assistance portion for {cursor:%B %Y}", created_by=request.user).id)
        cursor = date(cursor.year + (1 if cursor.month == 12 else 0), 1 if cursor.month == 12 else cursor.month + 1, 1)
    return Response({"detail": f"Rebuilt split rent: removed {removed} generated rent row(s), created {len(created)} payer-specific row(s).", "created_entry_ids": created, "buckets": _bucket_summary(tenant), "account": _tenant_account(tenant)})

def _tenant_payments_through(tenant, start, cutoff):
    total = Decimal("0.00")
    for entry in tenant.ledger_entries.filter(entry_date__gte=start, entry_date__lte=cutoff):
        if entry.entry_type in {PMLedgerEntry.EntryType.PAYMENT, PMLedgerEntry.EntryType.CREDIT} and _bucket(entry) == "TENANT" and entry.category != "SECURITY_DEPOSIT": total += entry.amount
    return total

@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def generate_installment_late_fees(request, tenant_id):
    workspace = _workspace(request); tenant = _tenant(workspace, tenant_id)
    if not tenant: return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)
    profile = _profile(tenant)
    if not profile.get("installment_schedule_enabled"): return Response({"detail": "Enable the tenant installment schedule first."}, status=status.HTTP_400_BAD_REQUEST)
    anchor = _date(profile.get("installment_anchor_date")); amount = _money(profile.get("installment_amount")); fee = _money(profile.get("installment_late_fee_amount"))
    if not anchor or amount <= 0 or fee <= 0: return Response({"detail": "Add the first installment due date, installment amount, and late fee."}, status=status.HTTP_400_BAD_REQUEST)
    through = _date(request.data.get("through_date")) or timezone.localdate(); grace = int(profile.get("installment_grace_days") or 0); step = 7 if str(profile.get("installment_frequency")).upper() == "WEEKLY" else 14; created=[]; due=anchor; installment_number=1
    while due <= through:
        check_date = due + timedelta(days=grace)
        if check_date <= through:
            required = amount * installment_number; paid = _tenant_payments_through(tenant, anchor - timedelta(days=31), check_date)
            if paid < required:
                ref = f"AUTO-INSTALLMENT-LATE-{tenant.id}-{due.isoformat()}"
                if not tenant.ledger_entries.filter(reference=ref).exists(): created.append(PMLedgerEntry.objects.create(workspace=workspace, tenant=tenant, lease=_active_lease(tenant), entry_date=check_date + timedelta(days=1), entry_type=PMLedgerEntry.EntryType.CHARGE, amount=fee, category="LATE_FEE", reference=ref, memo=f"Late fee for tenant installment due {due.isoformat()}", created_by=request.user).id)
        installment_number += 1; due += timedelta(days=step)
    return Response({"detail": f"Generated {len(created)} missed installment late fee(s) through {through.isoformat()}.", "created_entry_ids": created, "buckets": _bucket_summary(tenant), "account": _tenant_account(tenant)})