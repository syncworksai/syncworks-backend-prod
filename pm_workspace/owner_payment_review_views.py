"""Return provisional owner-reported monthly receipts without fabricating payment dates."""
from decimal import Decimal
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .billing_views import _workspace
from .models import PMDocumentPacket, PMTenant

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def owner_payment_review(request,tenant_id):
    ws=_workspace(request)
    tenant=PMTenant.objects.filter(workspace=ws,pk=tenant_id).first()
    if not tenant:return Response({"detail":"Tenant not found."},status=404)
    packet=PMDocumentPacket.objects.filter(
        workspace=ws,tenant=tenant,
        packet_type="ROXANA_2026_OWNER_REPORTED_PAYMENT_REVIEW").order_by("-id").first()
    if not packet:
        return Response({"report":None,"detail":"No owner-reported undated payments are pending review."})
    source=dict(packet.field_data or {})
    ledger=list(tenant.ledger_entries.filter(entry_type="PAYMENT").order_by("entry_date","id"))
    months=[]
    for row in source.get("monthly_payment_summary",[]):
        item=dict(row)
        month=item.get("month","")
        posted=sum((x.amount for x in ledger
                    if x.entry_date.strftime("%Y-%m")==month
                    and x.category!="RENT_HOUSING"
                    and x.payment_method!="HOUSING_AUTHORITY"),Decimal("0"))
        item["tenant_paid_already_posted"]=str(posted)
        item["tenant_payment_not_yet_posted"]=str(max(Decimal("0"),
            Decimal(str(item.get("reported_tenant_paid") or "0"))-posted)) if month!="2026-02" else "0.00"
        months.append(item)
    after=[x for x in months if x.get("month")!="2026-02"]
    pending=sum((Decimal(x["tenant_payment_not_yet_posted"]) for x in after),Decimal("0"))
    fees=sum((x.amount if x.entry_type in ("CHARGE","ADJUSTMENT") else -x.amount
              for x in tenant.ledger_entries.filter(category="LATE_FEE")
              if x.entry_type in ("CHARGE","ADJUSTMENT","CREDIT")),Decimal("0"))
    posted_balance=sum((x.amount if x.entry_type in ("CHARGE","ADJUSTMENT") else -x.amount
        for x in tenant.ledger_entries.exclude(category="RENT_HOUSING")
         if x.category.strip().upper().replace(" ","_")!="SECURITY_DEPOSIT"
         and x.payment_method!="HOUSING_AUTHORITY"),Decimal("0"))
    return Response({"report":{
        "months":months,"reported_by_owner":True,
        "pending_tenant_receipts_without_dated_transactions":str(pending),
        "posted_tenant_balance":str(posted_balance),
        "provisional_tenant_balance_if_verified":str(posted_balance-pending),
        "existing_late_fees":str(fees),
        "potential_additional_late_fees_unposted":source.get("max_additional_late_fees_to_review","0.00"),
        "housing_separate":source.get("mha_unreceived_from_march_to_september","0.00"),
        "security_deposit_applied":"0.00",
        "status":"RECEIPT_MATCHING_PENDING" if pending else "RECEIPTS_MATCH_LEDGER",
        "source_note":source.get("source_note",""),
        "notice":"Pending monthly payments change only the provisional balance, not the posted ledger, until individual bank receipt dates and amounts are recorded. Existing $50 late fees remain unchanged."
    }})
