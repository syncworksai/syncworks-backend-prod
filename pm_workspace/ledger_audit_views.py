"""Read-only FIFO rent allocations and documentary external-payment reconciliation.

Amounts reported as paid to a former manager or held by an authority are NOT ledger
PAYMENTs. Only receipts actually entered as payments can reduce tenant balances.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import calendar
import re
import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .billing_views import _workspace, _tenant_for_workspace, _profile, _active_lease, _signed, _profile_packet
from .models import PMDocumentPacket, PMLedgerEntry

CENT = Decimal("0.01")
CASE_TYPE = "TENANT_EXTERNAL_PAYMENT_RECONCILIATION"
EXTERNAL_TYPES = {
    "HAP_PAID_TO_FORMER_MANAGER", "HAP_ON_HOLD", "HAP_RETURN_CLAIM",
    "FORMER_MANAGER_DISTRIBUTION", "TENANT_PAID_FORMER_MANAGER",
    "DEPOSIT_COLLECTION_CLAIM", "DEPOSIT_TRANSFER_CLAIM", "DEPOSIT_APPLIED_CLAIM",
    "OTHER_UNVERIFIED",
}
EVIDENCE = {"UNVERIFIED", "REPORTED", "DOCUMENTED", "DISPUTED", "RESOLVED"}


def dollars(value):
    try:
        parsed = Decimal(str(value)).quantize(CENT)
    except (TypeError, InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() and CENT <= parsed <= Decimal("999999999.99") else None


def _bucket(entry):
    return "HOUSING" if entry.category == "RENT_HOUSING" or entry.payment_method == PMLedgerEntry.Method.HOUSING_AUTHORITY else "TENANT"


def _allocation(rows, cutoff=None):
    """Reconstruct allocation, oldest eligible charge first, separated by payer.

    Reconciliation credits reverse the indicated rent period. They do not
    accidentally extinguish an older charge unrelated to the correction.
    """
    obligations = []
    receipts = []
    for row in rows:
        if cutoff and row.entry_date > cutoff:
            continue
        if row.category.strip().upper().replace(" ", "_") == "SECURITY_DEPOSIT":
            continue  # held escrow is not current rent income
        if row.entry_type == PMLedgerEntry.EntryType.PAYMENT:
            receipts.append(row)
        elif row.entry_type in (PMLedgerEntry.EntryType.CHARGE, PMLedgerEntry.EntryType.ADJUSTMENT):
            obligations.append({"id": row.id, "entry_date": row.entry_date, "category": row.category,
                                "payer": _bucket(row), "original": row.amount, "remaining": row.amount})
    obligations.sort(key=lambda x: (x["entry_date"], x["id"]))
    # Credits are applied to the specific rent period when they arise from
    # audited rent split corrections; other credit entries use oldest-first.
    credit_rows = [row for row in rows if row.entry_type == PMLedgerEntry.EntryType.CREDIT
                   and row.category.strip().upper().replace(" ", "_") != "SECURITY_DEPOSIT" and (not cutoff or row.entry_date <= cutoff)]
    receipt_events = [(r.entry_date, r.id, "PAYMENT" if r.entry_type == PMLedgerEntry.EntryType.PAYMENT else "CREDIT", r)
                      for r in receipts + credit_rows]
    receipt_events.sort(key=lambda x: (x[0], x[1]))
    applied = []
    unapplied = {"TENANT": Decimal("0.00"), "HOUSING": Decimal("0.00")}
    for _, __, kind, source in receipt_events:
        payer = _bucket(source)
        remaining = source.amount
        target_month = None
        if kind == "CREDIT" and source.reference.startswith("RECON-") and source.category in ("RENT", "RENT_TENANT", "RENT_HOUSING"):
            found = re.search(r"RECON-\d+-(\d{4}-\d{2})-", source.reference)
            target_month = found.group(1) if found else None
        candidates = [x for x in obligations if x["payer"] == payer and x["remaining"] > 0]
        if target_month:
            candidates = [x for x in candidates if x["entry_date"].strftime("%Y-%m") == target_month
                          and x["category"] in ("RENT", "RENT_TENANT", "RENT_HOUSING")]
        for debt in candidates:
            if remaining <= 0:
                break
            part = min(debt["remaining"], remaining)
            debt["remaining"] -= part
            remaining -= part
            applied.append({"source_id": source.id, "source_date": str(source.entry_date),
                            "source_type": kind, "charge_id": debt["id"],
                            "charge_month": debt["entry_date"].strftime("%Y-%m"),
                            "category": debt["category"], "payer": payer, "amount": str(part)})
        if remaining > 0:
            unapplied[payer] += remaining
    return {"obligations": obligations, "allocations": applied, "unapplied": unapplied}


def _json_allocation(analysis):
    return {
        "allocations": analysis["allocations"],
        "outstanding": [
            {"entry_id": d["id"], "date": str(d["entry_date"]), "category": d["category"],
             "payer": d["payer"], "original": str(d["original"]), "unpaid": str(d["remaining"])}
            for d in analysis["obligations"] if d["remaining"] > 0
        ],
        "tenant_unpaid": str(sum((d["remaining"] for d in analysis["obligations"] if d["payer"] == "TENANT"), Decimal("0"))),
        "housing_unpaid": str(sum((d["remaining"] for d in analysis["obligations"] if d["payer"] == "HOUSING"), Decimal("0"))),
        "unapplied_tenant_receipts": str(analysis["unapplied"]["TENANT"]),
        "unapplied_housing_receipts": str(analysis["unapplied"]["HOUSING"]),
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def oldest_first_allocation(request, tenant_id):
    tenant = _tenant_for_workspace(_workspace(request), tenant_id)
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)
    ledger = list(tenant.ledger_entries.order_by("entry_date", "id"))
    analysis = _allocation(ledger)
    profile = _profile(tenant)
    due_day = max(1, min(28, int(profile.get("rent_due_day") or 1)))
    grace = max(0, min(31, int(profile.get("grace_days") or 0)))
    end = timezone.localdate()
    months = sorted({(r.entry_date.year, r.entry_date.month) for r in ledger
                     if r.category in ("RENT", "RENT_TENANT") and r.entry_type == "CHARGE"
                     and r.entry_date <= end})
    fee_checks = []
    for year, month in months:
        due = date(year, month, min(due_day, calendar.monthrange(year, month)[1]))
        check_date = due + timedelta(days=grace)
        if check_date >= end:
            continue
        has_fee = any(r.category == "LATE_FEE" and r.entry_type == "CHARGE"
                      and r.entry_date.year == year and r.entry_date.month == month for r in ledger)
        snapshot = _allocation(ledger, cutoff=check_date)
        unpaid_rent = sum((d["remaining"] for d in snapshot["obligations"]
                          if d["payer"] == "TENANT" and d["category"] in ("RENT", "RENT_TENANT")
                          and d["entry_date"].year == year and d["entry_date"].month == month), Decimal("0"))
        fee_checks.append({"month": f"{year:04d}-{month:02d}", "late_fee_already_recorded": has_fee,
                           "tenant_rent_unpaid_at_grace": str(unpaid_rent),
                           "review_late_fee": bool(unpaid_rent > 0 and not has_fee),
                           "note": "Review signed lease, grace period, prior receipts and adjustments before charging."})
    return Response({"allocation_method": "OLDEST_ELIGIBLE_CHARGE_FIRST_BY_PAYER",
                     "payment_dates_unchanged": True,
                     **_json_allocation(analysis), "late_fee_review": fee_checks})


def _external_packet(tenant, create=False):
    packet = tenant.document_packets.filter(packet_type=CASE_TYPE).order_by("-id").first()
    if packet or not create:
        return packet
    return PMDocumentPacket.objects.create(
        workspace=tenant.workspace, tenant=tenant,
        lease=_active_lease(tenant), packet_type=CASE_TYPE,
        template_name="External payment evidence log", template_version="1",
        field_data={"records": []},
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def external_payment_evidence(request, tenant_id):
    tenant = _tenant_for_workspace(_workspace(request), tenant_id)
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "GET":
        packet = _external_packet(tenant)
        return Response({"records": (packet.field_data or {}).get("records", []) if packet else [],
                         "affects_ledger_balance": False})
    category = str(request.data.get("category") or "").upper()
    evidence = str(request.data.get("evidence_status") or "UNVERIFIED").upper()
    paid_month = str(request.data.get("period") or "")
    amount = dollars(request.data.get("amount"))
    note = str(request.data.get("note") or "").strip()
    if category not in EXTERNAL_TYPES or evidence not in EVIDENCE or not amount:
        return Response({"detail": "Select a valid external record type, evidence status and positive amount."}, status=400)
    if not (len(paid_month) == 7 and paid_month[4] == "-" and paid_month[:4].isdigit() and paid_month[5:].isdigit() and 1 <= int(paid_month[5:]) <= 12):
        return Response({"detail": "Period must be YYYY-MM."}, status=400)
    if len(note) < 8:
        return Response({"detail": "Describe where the information came from."}, status=400)
    if category == "DEPOSIT_APPLIED_CLAIM" and evidence == "RESOLVED":
        return Response({"detail": "A confirmed deposit application must be reconciled against the deposit account; this evidence log cannot mark it resolved or pay rent."}, status=400)
    packet = _external_packet(tenant, create=True)
    data = dict(packet.field_data or {})
    records = list(data.get("records") or [])
    row = {"id": str(uuid.uuid4()), "period": paid_month, "amount": str(amount),
           "category": category, "evidence_status": evidence, "note": note,
           "recorded_at": timezone.now().isoformat(), "recorded_by": request.user.pk}
    records.append(row)
    data["records"] = records
    packet.field_data = data
    packet.save(update_fields=["field_data", "updated_at"])
    return Response({"record": row, "records": records, "affects_ledger_balance": False}, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def verified_monthly_late_fee(request, tenant_id):
    """Preview/apply a single documented fee for an unpaid tenant rent portion.

    Never assess a fee for MHA's unpaid share, and never duplicate a fee
    already recorded for the same rental month.
    """
    tenant = _tenant_for_workspace(_workspace(request), tenant_id)
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=404)
    month = str(request.data.get("month") or "")
    try:
        start = date.fromisoformat(month + "-01")
        if start.strftime("%Y-%m") != month:
            raise ValueError()
    except ValueError:
        return Response({"detail": "Enter a valid YYYY-MM month."}, status=400)
    profile = _profile(tenant)
    due_day = request.data.get("due_day", profile.get("rent_due_day") or 1)
    grace = request.data.get("grace_days", profile.get("grace_days") or 0)
    try:
        due_day, grace = int(due_day), int(grace)
    except (ValueError, TypeError):
        return Response({"detail": "Enter an integer rent due day and grace days."}, status=400)
    if not (1 <= due_day <= 28 and 0 <= grace <= 31):
        return Response({"detail": "Due day must be 1–28 and grace days 0–31."}, status=400)
    cutoff = date(start.year, start.month, due_day) + timedelta(days=grace)
    fee_day = cutoff + timedelta(days=1)
    if fee_day > timezone.localdate():
        return Response({"detail": "This late fee is not due yet."}, status=400)
    fee = dollars(request.data.get("amount"))
    if not fee:
        return Response({"detail": "Provide the late-fee amount from the signed lease."}, status=400)
    source = str(request.data.get("source_note") or "").strip()
    if len(source) < 12:
        return Response({"detail": "Cite the signed lease clause and relevant payment dates."}, status=400)
    rows = list(tenant.ledger_entries.select_for_update().order_by("entry_date", "id"))
    existing = [x for x in rows if x.category == "LATE_FEE"
                and (x.reference.endswith(f"-{month}") or (x.entry_date.year, x.entry_date.month) == (start.year, start.month))
                and x.entry_type in ("CHARGE", "ADJUSTMENT")]
    if existing:
        return Response({"detail": f"A late fee is already recorded for {month}; verify before adding another.",
                         "existing_fee_ids": [x.id for x in existing]}, status=409)
    tenant_month_rent = [x for x in rows if x.entry_type == "CHARGE"
                         and x.category in ("RENT", "RENT_TENANT")
                         and (x.entry_date.year, x.entry_date.month) == (start.year, start.month)]
    if not tenant_month_rent:
        return Response({"detail": "Post/reconcile tenant rent for this month before reviewing its late fee."}, status=409)
    as_of = _allocation(rows, cutoff=cutoff)
    outstanding = sum((o["remaining"] for o in as_of["obligations"]
                       if o["payer"] == "TENANT" and o["category"] in ("RENT", "RENT_TENANT")
                       and (o["entry_date"].year, o["entry_date"].month) == (start.year, start.month)),
                      Decimal("0.00"))
    eligible_for_review = outstanding > 0
    preview = {"month": month, "fee_date": str(fee_day), "unpaid_tenant_rent_at_grace": str(outstanding),
               "fee": str(fee), "eligible_for_review": eligible_for_review,
               "applied": False, "note": "Lease terms, payment timing and legal eligibility must be confirmed by the owner."}
    if request.data.get("apply") is not True:
        return Response(preview)
    if not eligible_for_review:
        return Response({"detail": "Tenant rent was paid by the configured grace deadline; no late fee may be posted by this workflow."}, status=409)
    if request.data.get("lease_verified") is not True or request.data.get("confirmed") is not True:
        return Response({"detail": "Verify the signed lease provision, payment dates and amount before applying."}, status=400)
    entry = PMLedgerEntry.objects.create(
        workspace=tenant.workspace, tenant=tenant, lease=_active_lease(tenant),
        entry_date=fee_day, entry_type=PMLedgerEntry.EntryType.CHARGE,
        amount=fee, category="LATE_FEE", reference=f"VERIFIED-LATE-{tenant.id}-{month}",
        memo=f"Reviewed lease fee for {month}: {source}", created_by=request.user,
    )
    return Response({**preview, "applied": True, "ledger_entry_id": entry.id})
