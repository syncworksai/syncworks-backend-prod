"""Lease-first recurring rent billing, payer schedules, and auditable late-fee waivers.

The original lease effective date and the date this manager began billing are
distinct. Housing shares use explicit month overrides for prior determinations.
No security-deposit entries are created by this engine.
"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import calendar

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .billing_views import _workspace, _active_lease, _profile_packet, _tenant_account
from .ledger_audit_views import _allocation, _json_allocation
from .models import PMDocumentPacket, PMTenant, PMLease, PMLedgerEntry

PACKET = "LEASE_AUTOMATED_BILLING"
RENT_CATEGORIES = ("RENT","RENT_TENANT","RENT_HOUSING")
MAX_MONTHS = 36

def dec(raw):
    try:
        value = Decimal(str(raw)).quantize(Decimal("0.01"))
        if not value.is_finite() or not Decimal("0") <= value <= Decimal("999999999.99"):
            return None
        return value
    except (ValueError, TypeError, InvalidOperation):
        return None

def month_date(string):
    try:
        dt=date.fromisoformat(str(string)+"-01")
        return dt if dt.strftime("%Y-%m")==string else None
    except (ValueError, TypeError):
        return None

def first(day):
    return date(day.year,day.month,1)

def months_between(a,b):
    cur=first(a)
    end=first(b)
    i=0
    while cur<=end and i<MAX_MONTHS:
        yield cur
        cur=date(cur.year+int(cur.month==12),1 if cur.month==12 else cur.month+1,1)
        i+=1

def signed(entry):
    return entry.amount if entry.entry_type in ("CHARGE","ADJUSTMENT") else -entry.amount

def current_settings(lease):
    tenant = dec(lease.tenant_portion) if lease.section8 else dec(lease.monthly_rent)
    housing = dec(lease.assistance_portion) if lease.section8 else Decimal("0")
    return (dec(lease.monthly_rent), tenant, housing)

def get_setup(tenant):
    p=tenant.document_packets.filter(packet_type=PACKET).order_by("-id").first()
    return p, (p.field_data if p and isinstance(p.field_data,dict) else {})

def normalize_setup(payload,lease):
    rent,tpart,hpart=current_settings(lease)
    if rent is None or rent<=0:
        raise ValueError("Set the verified lease rent first.")
    try:
        billing_start=date.fromisoformat(str(payload.get("billing_start_date")))
        due_day=int(payload.get("due_day",1))
        grace=int(payload.get("grace_days",5))
    except (TypeError,ValueError):
        raise ValueError("Enter a valid billing start date, due day and grace period.")
    if not 1<=due_day<=28 or not 0<=grace<=30:
        raise ValueError("Due day must be 1–28 and grace period 0–30.")
    if billing_start<lease.start_date or billing_start>timezone.localdate()+timedelta(days=366):
        raise ValueError("Billing cannot start before lease start or more than one year in the future.")
    fee=dec(payload.get("late_fee_amount",0))
    if fee is None:
        raise ValueError("Enter a valid late fee.")
    active=payload.get("active") is True
    fee_auto=payload.get("auto_late_fees") is True
    if fee_auto and not payload.get("late_fee_verified"):
        raise ValueError("Automatic late fees require written lease-clause verification.")
    auto_fee_from=str(payload.get("auto_late_fee_from") or timezone.localdate())
    try: auto_fee_from_date=date.fromisoformat(auto_fee_from)
    except ValueError:raise ValueError("Late-fee auto-start must be a valid date.")
    if fee_auto and auto_fee_from_date<timezone.localdate():
        raise ValueError("Automatic late-fee start cannot be backdated. Review historical fees individually.")
    source=str(payload.get("source_note") or "").strip()
    if len(source)<12:
        raise ValueError("Describe the signed lease or verified rent determination (12+ characters).")
    horizon=str(payload.get("verified_through") or "")
    if lease.section8 and active and not month_date(horizon):
        raise ValueError("Assisted billing requires a verified-through month. Extend it after an approved determination.")
    if not lease.section8:
        horizon=""
    raw=payload.get("monthly_overrides") or {}
    if not isinstance(raw,dict) or len(raw)>MAX_MONTHS:
        raise ValueError("Enter at most 36 reviewed month allocations.")
    overrides={}
    for label,item in raw.items():
        dt=month_date(label)
        if not dt or dt<first(billing_start):
            raise ValueError("Monthly allocations must be valid and not predate billing start.")
        if not isinstance(item,dict):
            raise ValueError("Invalid monthly allocation.")
        tr=dec(item.get("tenant"))
        hr=dec(item.get("housing",0))
        abated=dec(item.get("abated",0))
        if None in (tr,hr,abated) or tr+hr+abated!=rent:
            raise ValueError(f"{label}: tenant + housing + abated must equal the contract rent.")
        note=str(item.get("note") or "").strip()
        if abated and len(note)<8:
            raise ValueError(f"{label}: explain the abated or excluded housing amount.")
        if not lease.section8 and (hr or abated):
            raise ValueError("A non-assisted lease cannot allocate rent to an assistance payer.")
        overrides[label]={"tenant":str(tr),"housing":str(hr),"abated":str(abated),"note":note[:600]}
    if lease.section8 and tpart is not None and hpart is not None and tpart+hpart!=rent:
        raise ValueError("Current lease tenant plus housing split must equal contract rent.")
    return {"active":active,"billing_start_date":billing_start.isoformat(),
        "due_day":due_day,"grace_days":grace,"late_fee_amount":str(fee),
        "auto_late_fees":fee_auto,"late_fee_verified":bool(payload.get("late_fee_verified")),
        "auto_late_fee_from":str(auto_fee_from_date),
        "source_note":source[:900],"verified_through":horizon,
        "monthly_overrides":overrides,
        "updated_at":timezone.now().isoformat()}

def plan(tenant,lease,config,as_of):
    start=date.fromisoformat(config["billing_start_date"])
    rent,default_tenant,default_housing=current_settings(lease)
    override=config.get("monthly_overrides") or {}
    horizon=month_date(config.get("verified_through")) if lease.section8 else None
    rows=[]
    for m in months_between(start,as_of):
        due=date(m.year,m.month,min(int(config["due_day"]),calendar.monthrange(m.year,m.month)[1]))
        if due<start or due>as_of:continue
        label=m.strftime("%Y-%m")
        match=override.get(label)
        if match:
            tenant_due=Decimal(match["tenant"]);housing_due=Decimal(match["housing"])
            abated=Decimal(match["abated"]);reason=match.get("note","")
        else:
            if lease.section8 and (not horizon or m>horizon):
                rows.append({"month":label,"due_date":str(due),"blocked":True,
                    "reason":"Assistance split requires renewal or agency verification before billing."})
                continue
            tenant_due=default_tenant;housing_due=default_housing;abated=Decimal("0")
            reason="Current certified split" if lease.section8 else "Lease rent"
        if None in (tenant_due,housing_due) or tenant_due+housing_due+abated!=rent:
            rows.append({"month":label,"blocked":True,"reason":"Rent split is inconsistent with lease."})
            continue
        rows.append({"month":label,"due_date":str(due),"blocked":False,
           "rent":str(rent),"tenant_due":str(tenant_due),"housing_due":str(housing_due),
           "abated":str(abated),"reason":reason})
    return rows

def preview_rows(tenant,lease,config,through):
    entries=list(tenant.ledger_entries.order_by("entry_date","id"))
    rows=plan(tenant,lease,config,through)
    for row in rows:
        if row["blocked"]:continue
        month=row["month"]
        current_t=Decimal("0"); current_h=Decimal("0")
        paid_t=Decimal("0");paid_h=Decimal("0");late_charged=Decimal("0")
        for entry in entries:
            if entry.entry_date.strftime("%Y-%m")!=month:continue
            if entry.entry_type=="PAYMENT":
                if entry.payment_method=="HOUSING_AUTHORITY" or entry.category=="RENT_HOUSING":
                    paid_h+=entry.amount
                else:paid_t+=entry.amount
            elif entry.category in RENT_CATEGORIES:
                if entry.category=="RENT_HOUSING":current_h+=signed(entry)
                else:current_t+=signed(entry)
            elif entry.category=="LATE_FEE":
                late_charged+=signed(entry)
        row.update({"posted_tenant":str(current_t),"posted_housing":str(current_h),
            "adjust_tenant":str(Decimal(row["tenant_due"])-current_t),
            "adjust_housing":str(Decimal(row["housing_due"])-current_h),
            "tenant_receipts_month":str(paid_t),"housing_receipts_month":str(paid_h),
            "late_fee_net_month":str(late_charged)})
    return rows

def apply_rent(tenant,lease,config,through,actor=None,only_month=None):
    rows=preview_rows(tenant,lease,config,through)
    created=[]
    for row in rows:
        if row["blocked"] or (only_month and row["month"]!=only_month):continue
        for payer,key,col in (("TENANT","adjust_tenant","RENT_TENANT"),("HOUSING","adjust_housing","RENT_HOUSING")):
            delta=Decimal(row[key])
            if delta==0:continue
            # Never delete or rewrite imported statements or payments; balancing adjustments.
            reference=f"LEASE-BILL-{tenant.id}-{row['month']}-{payer}-{timezone.now():%Y%m%d%H%M%S%f}"
            item=PMLedgerEntry.objects.create(workspace=tenant.workspace,tenant=tenant,lease=lease,
                entry_date=date.fromisoformat(row["due_date"]),
                entry_type="CHARGE" if delta>0 else "CREDIT",
                category=col,amount=abs(delta),reference=reference,
                memo=f"Lease monthly billing {row['month']}, {payer} share; verified source: {config['source_note']}. "+
                     (f"Assistance excluded {row['abated']}: {row['reason']}." if Decimal(row["abated"]) else ""),
                created_by=actor)
            created.append(item.id)
    return rows,created

def late_fee_preview(tenant,lease,config,through):
    entries=list(tenant.ledger_entries.order_by("entry_date","id"))
    rows=plan(tenant,lease,config,through)
    due=[]
    for row in rows:
        if row["blocked"]:continue
        mo=row["month"]
        grace_end=date.fromisoformat(row["due_date"])+timedelta(days=int(config["grace_days"]))
        fee_date=grace_end+timedelta(days=1)
        if fee_date>through:continue
        if any(e.category=="LATE_FEE" and (e.entry_date.strftime("%Y-%m")==mo or
            e.reference.endswith("-"+mo)) and e.entry_type=="CHARGE" for e in entries):
            continue
        if any(e.reference.startswith("LATE-WAIVE-") and e.entry_date.strftime("%Y-%m")==mo for e in entries):
            continue
        snap=_allocation(entries,cutoff=grace_end)
        unpaid=sum((x["remaining"] for x in snap["obligations"]
            if x["payer"]=="TENANT" and x["category"] in ("RENT","RENT_TENANT")
            and x["entry_date"].strftime("%Y-%m")==mo),Decimal("0"))
        if unpaid>0:
            due.append({"month":mo,"date":str(fee_date),"amount":str(config["late_fee_amount"]),
                        "unpaid_tenant_at_grace":str(unpaid)})
    return due

@api_view(["GET","PATCH","POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def lease_billing(request,tenant_id):
    workspace=_workspace(request)
    tenant=PMTenant.objects.select_for_update().filter(workspace=workspace,pk=tenant_id).first()
    if not tenant:return Response({"detail":"Tenant not found."},status=404)
    lease=_active_lease(tenant)
    if not lease:return Response({"detail":"Add an active lease first."},status=400)
    lease=PMLease.objects.select_for_update().get(pk=lease.pk)
    packet,data=get_setup(tenant)
    if request.method=="PATCH":
        try:config=normalize_setup(request.data,lease)
        except ValueError as exc:return Response({"detail":str(exc)},status=400)
        if not packet:
            packet=PMDocumentPacket.objects.create(workspace=workspace,tenant=tenant,lease=lease,
                packet_type=PACKET,template_name="Lease-based recurring billing",field_data=config)
        else:
            packet.field_data=config;packet.lease=lease
            packet.save(update_fields=["field_data","lease","updated_at"])
        return Response({"setup":config,"detail":"Lease billing schedule saved. No existing financial entry changed."})
    if not data:
        data={"active":False,"billing_start_date":max(lease.start_date,timezone.localdate().replace(day=1)).isoformat(),
              "due_day":1,"grace_days":5,"late_fee_amount":"0.00","auto_late_fees":False,
              "late_fee_verified":False,"auto_late_fee_from":str(timezone.localdate()),
              "verified_through":"","monthly_overrides":{},"source_note":""}
    if request.method=="GET":
        return Response({"setup":data,"lease":{"id":lease.id,"start_date":str(lease.start_date),
            "end_date":str(lease.end_date) if lease.end_date else None,"status":lease.status,
            "contract_rent":str(lease.monthly_rent),"tenant_portion":str(lease.tenant_portion or 0),
            "housing_portion":str(lease.assistance_portion or 0),"section8":lease.section8},
            "account":_tenant_account(tenant),"notice":"Preview is read-only. Unverified assistance receipts and security deposits are never marked paid."})
    if not packet or not data.get("active"):
        return Response({"detail":"Save and activate a reviewed lease billing setup before posting."},status=409)
    try:through=date.fromisoformat(str(request.data.get("through_date") or timezone.localdate()))
    except ValueError:return Response({"detail":"Valid through date required."},status=400)
    if through>timezone.localdate() or (through-first(date.fromisoformat(data["billing_start_date"]))).days>1120:
        return Response({"detail":"Only due months in the past 36 months can be billed here."},status=400)
    rows=preview_rows(tenant,lease,data,through)
    fees=late_fee_preview(tenant,lease,data,through) if data.get("late_fee_verified") else []
    if request.data.get("apply") is not True:
        return Response({"applied":False,"months":rows,"late_fee_candidates":fees,
            "rent_paid_vs_owed":_json_allocation(_allocation(list(tenant.ledger_entries.all()))),
            "notice":"Payment dates, prior late fees and separate deposit records are not changed by rent billing."})
    if request.data.get("confirmed") is not True:
        return Response({"detail":"Confirm the monthly payer amounts and source documentation."},status=400)
    _,created=apply_rent(tenant,lease,data,through,actor=request.user)
    # Fees are separate and opt-in. Never backdate new late fees automatically
    # in this historical-reconciliation endpoint.
    return Response({"applied":True,"created_entry_ids":created,"months":preview_rows(tenant,lease,data,through),
        "rent_paid_vs_owed":_json_allocation(_allocation(list(tenant.ledger_entries.all()))),
        "notice":"Only rent adjustments posted. Late fees remain available for individual, verified review."})

@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def waive_late_fee(request,tenant_id,fee_id):
    workspace=_workspace(request)
    tenant=PMTenant.objects.select_for_update().filter(workspace=workspace,pk=tenant_id).first()
    fee=PMLedgerEntry.objects.select_for_update().filter(workspace=workspace,tenant=tenant,
         id=fee_id,category="LATE_FEE",entry_type="CHARGE").first() if tenant else None
    if not fee:return Response({"detail":"Late fee not found."},status=404)
    ref=f"LATE-WAIVE-{fee.id}"
    if tenant.ledger_entries.filter(reference=ref).exists():
        return Response({"detail":"Late fee already waived."},status=409)
    reason=str(request.data.get("reason") or "").strip()
    if len(reason)<5 or request.data.get("confirmed") is not True:
        return Response({"detail":"Provide a reason and confirm the waiver."},status=400)
    amount=dec(request.data.get("amount",fee.amount))
    if amount is None or amount<=0 or amount>fee.amount:
        return Response({"detail":"Waiver must be positive and no more than the original fee."},status=400)
    item=PMLedgerEntry.objects.create(workspace=workspace,tenant=tenant,lease=fee.lease,
        entry_date=timezone.localdate(),entry_type="CREDIT",amount=amount,
        category="LATE_FEE",reference=ref,memo=f"Waiver of fee #{fee.id}: {reason[:300]}",
        created_by=request.user)
    return Response({"credit_entry_id":item.id,"waived_fee_id":fee.id,"amount":str(amount),
        "detail":"Late fee waived by auditable credit. Original fee retained."},status=201)
