"""Simple owner-entered monthly rent split schedule.

Drafts carry no ledger effect. The assisted payer's amounts must be verified
against provider determinations before any month is posted. Tenant charge
reconciliation is performed independently via the existing audited endpoint.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .billing_views import _workspace
from .models import PMDocumentPacket, PMTenant

KIND = "PM_SIMPLE_MONTHLY_RENT_SCHEDULE"

def _amount(raw):
    try:
        val=Decimal(str(raw)).quantize(Decimal("0.01"))
        if not val.is_finite() or val<0 or val>Decimal("9999999.99"):return None
        return val
    except (ValueError,TypeError,InvalidOperation):
        return None

@api_view(["GET","PATCH"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def simple_monthly_rent_schedule(request,tenant_id):
    workspace=_workspace(request)
    tenant=PMTenant.objects.select_for_update().filter(workspace=workspace,pk=tenant_id).first()
    if not tenant:return Response({"detail":"Tenant not found."},status=404)
    packet=PMDocumentPacket.objects.filter(workspace=workspace,tenant=tenant,packet_type=KIND).order_by("-id").first()
    if request.method=="GET":
        return Response({"schedule":packet.field_data if packet else None,
                         "notice":"An entered schedule is a draft. It does not change the signed lease, charges, payment records, or verified housing share."})
    rows=request.data.get("months")
    if not isinstance(rows,list) or not (1<=len(rows)<=36):
        return Response({"detail":"Enter 1–36 monthly rent rows."},status=400)
    clean=[];seen=set()
    for row in rows:
        if not isinstance(row,dict):return Response({"detail":"Invalid month."},status=400)
        label=str(row.get("month") or "")
        try:
            month=date.fromisoformat(label+"-01")
            if month.strftime("%Y-%m")!=label:raise ValueError()
        except ValueError:return Response({"detail":"Use valid YYYY-MM months."},status=400)
        if label in seen:return Response({"detail":f"Duplicate month {label}."},status=400)
        seen.add(label)
        rent=_amount(row.get("rent"))
        housing=_amount(row.get("mha"))
        if rent is None or rent<=0 or housing is None or housing>rent:
            return Response({"detail":f"{label}: total rent must be positive and MHA share between $0 and total rent."},status=400)
        clean.append({"month":label,"rent":str(rent),"mha":str(housing),
                      "tenant":str(rent-housing),
                      "source_status":str(row.get("status") or "PROPOSED")[:70]})
    note=str(request.data.get("source_note") or "").strip()
    if len(note)<12 or len(note)>2000:
        return Response({"detail":"Add a source note describing the proposed monthly allocations (12–2000 characters)."},status=400)
    clean.sort(key=lambda item:item["month"])
    data={"months":clean,"source_note":note,"status":"DRAFT_NOT_POSTED",
          "last_saved_by":request.user.pk,"last_saved_at":timezone.now().isoformat(),
          "notice":"Saved for review only. No rent, housing payment, late fee or deposit was posted."}
    if packet:
        packet.field_data=data
        packet.save(update_fields=["field_data","updated_at"])
    else:
        PMDocumentPacket.objects.create(workspace=workspace,tenant=tenant,
          packet_type=KIND,template_name="Simple monthly rent and housing allocation draft",
          field_data=data)
    return Response({"schedule":data,"detail":"Monthly schedule saved as a draft. The ledger is unchanged."})
