"""Original lease amount corrections and read-only historical monthly comparison.

This does not alter a rent-increase timeline, past due amounts, late fees, payment
allocation, or agency share. A separate, reviewed monthly reconciliation is needed.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
import calendar
from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .billing_views import _workspace, _tenant_for_workspace, _active_lease, _signed
from .models import PMDocumentPacket, PMLedgerEntry
from .document_models import PMPropertyDocument

PACKET="ORIGINAL_LEASE_RENT_AUDIT"

def _amount(raw):
    try:x=Decimal(str(raw)).quantize(Decimal("0.01"))
    except (ValueError,InvalidOperation,TypeError):return None
    return x if x.is_finite() and Decimal("0")<x<=Decimal("999999999.99") else None

def _monthly(tenant,lease,rent):
    today=timezone.localdate()
    current=date(lease.start_date.year,lease.start_date.month,1)
    final=min(today,lease.end_date or today)
    records=list(tenant.ledger_entries.filter(entry_date__gte=current,entry_date__lte=final,
                category__in=("RENT","RENT_TENANT","RENT_HOUSING")).order_by("entry_date","id"))
    months=[]
    for count in range(36):
        if current>final:break
        records_here=[x for x in records if (x.entry_date.year,x.entry_date.month)==(current.year,current.month)]
        posted=sum((_signed(x) for x in records_here if x.entry_type!="PAYMENT"),Decimal("0.00"))
        diff=rent-posted
        months.append({"month":current.strftime("%Y-%m"),"contract_rent":str(rent),
                       "posted_net_rent_charges":str(posted),"variance":str(diff),
                       "status":"MATCH" if diff==0 else "MISSING" if not records_here else "NEEDS_REVIEW",
                       "note":"Compare assistance share, abatements, prorations and approved rent changes before correcting."})
        current=date(current.year+1,1,1) if current.month==12 else date(current.year,current.month+1,1)
    return months

@api_view(["GET","POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def original_lease_rent_review(request,tenant_id):
    workspace=_workspace(request)
    tenant=_tenant_for_workspace(workspace,tenant_id)
    if not tenant:return Response({"detail":"Tenant not found."},status=404)
    lease=_active_lease(tenant)
    if not lease:return Response({"detail":"Create or connect the signed lease first."},status=400)
    audit=tenant.document_packets.filter(packet_type=PACKET).order_by("-updated_at","-id").first()
    if request.method=="GET":
        rent=lease.monthly_rent
        return Response({"lease_id":lease.id,"lease_start":str(lease.start_date),"lease_end":str(lease.end_date) if lease.end_date else None,
            "section8":lease.section8,"saved_original_rent":str(rent),"last_audit":audit.field_data if audit else None,
            "monthly_review":_monthly(tenant,lease,rent),"no_ledger_changes":True})
    proposed=_amount(request.data.get("contract_rent"))
    if proposed is None:return Response({"detail":"Contract rent must be a positive valid amount."},status=400)
    note=str(request.data.get("source_note") or "").strip()
    if len(note)<12:return Response({"detail":"Explain which signed lease verifies the original contract rent."},status=400)
    doc_id=request.data.get("source_document_id") or None
    if doc_id:
        d=PMPropertyDocument.objects.filter(workspace=workspace,pk=doc_id).first()
        if not d or d.tenant_id not in (None,tenant.id) or d.property.name.strip().lower()!=tenant.property_name.strip().lower():
            return Response({"detail":"Document must match the tenant's property and portfolio."},status=400)
    if request.data.get("effective_date") != lease.start_date.isoformat():
        return Response({"detail":"This tool corrects the ORIGINAL lease rent only. Effective date must match the signed lease start; use Rent Increases for later changes."},status=400)
    payload={
        "lease_id":lease.id,"old_original_rent":str(lease.monthly_rent),
        "proposed_original_rent":str(proposed),"effective_date":str(lease.start_date),
        "source_document_id":doc_id,"source_note":note,
        "monthly_review":_monthly(tenant,lease,proposed),
        "will_change_historical_ledger":False,"will_change_payer_allocation":False,
    }
    if request.data.get("apply") is not True:return Response({"preview":payload,"applied":False})
    if request.data.get("confirmed") is not True:
        return Response({"detail":"Explicitly confirm the original signed lease and effective date."},status=400)
    old=lease.monthly_rent
    if proposed!=old:
        lease.monthly_rent=proposed
        lease.save(update_fields=["monthly_rent","updated_at"])
        tenant.monthly_rent=proposed
        tenant.save(update_fields=["monthly_rent","updated_at"])
    history=list((audit.field_data or {}).get("history") or []) if audit else []
    history.append({"at":timezone.now().isoformat(),"by":request.user.pk,"previous":str(old),
                    "corrected":str(proposed),"source_note":note,"source_document_id":doc_id})
    if not audit:
        audit=PMDocumentPacket(workspace=workspace,tenant=tenant,lease=lease,packet_type=PACKET,
            template_name="Original lease contract rent audit")
    audit.field_data={"history":history[-100:],"latest_amount":str(proposed),"effective_date":str(lease.start_date)}
    audit.save()
    return Response({"applied":True,"saved_original_rent":str(proposed),
                     "detail":"Original lease amount updated with audit. Past ledger entries remain untouched.",
                     "monthly_review":_monthly(tenant,lease,proposed)})
