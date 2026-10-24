"""Store owner's revised February–October payment totals without inventing bank dates.

No money moves, no PAYMENT ledger entry is fabricated, and no late fees are
automatically imposed. Owner can match the March $2706 to actual bank receipts
and then enter them on their real dates in PM ledger.
"""
from django.db import migrations
from decimal import Decimal

MONTHS=[
 ("2026-02","208.00","130.00","78.00","FORMER_MANAGER_REPORTED"),
 ("2026-03","2706.00","2706.00","0.00","NEEDS_DATED_BANK_RECEIPTS"),
 ("2026-04","704.00","704.00","0.00","POSTED"),
 ("2026-05","900.00","900.00","0.00","POSTED"),
 ("2026-06","700.00","700.00","0.00","POSTED"),
 ("2026-07","800.00","800.00","0.00","POSTED"),
 ("2026-08","750.00","750.00","0.00","POSTED"),
 ("2026-09","750.00","750.00","0.00","POSTED"),
 ("2026-10","1200.00","1200.00","0.00","POSTED"),
]

def record_owner_report(apps,schema_editor):
    Tenant=apps.get_model("pm_workspace","PMTenant")
    Ledger=apps.get_model("pm_workspace","PMLedgerEntry")
    Packet=apps.get_model("pm_workspace","PMDocumentPacket")
    tenants=list(Tenant.objects.filter(first_name__iexact="Tonya",
                 last_name__iexact="English",property_name__iexact="Roxana",
                 workspace__name__iexact="Lord Holdings"))
    if len(tenants)!=1:return
    tenant=tenants[0]
    prior=Packet.objects.filter(tenant_id=tenant.pk,packet_type="ROXANA_2026_OWNER_APPROVED_RECONCILIATION").order_by("-id").first()
    if not prior:return
    existing=Packet.objects.filter(tenant_id=tenant.pk,packet_type="ROXANA_2026_OWNER_REPORTED_PAYMENT_REVIEW").first()
    if existing:return
    records=list(Ledger.objects.filter(tenant_id=tenant.pk,
                 entry_type="PAYMENT",entry_date__year=2026))
    rows=[]
    for month,all_paid,tenant_paid,housing_paid,status in MONTHS:
        posted=sum((r.amount for r in records
                     if r.entry_date.strftime("%Y-%m")==month
                     and r.payment_method!="HOUSING_AUTHORITY"
                     and r.category!="RENT_HOUSING"),Decimal("0"))
        # February was collected by former manager and is reflected in
        # the previously posted $1,277 opening-arrears charge.
        pending=(Decimal(tenant_paid)-posted) if month!="2026-02" else Decimal("0")
        rows.append({"month":month,"owner_reported_paid_total":all_paid,
            "reported_tenant_paid":tenant_paid,"reported_housing_paid":housing_paid,
            "tenant_paid_already_posted":str(posted),
            "tenant_payment_not_yet_posted":str(max(Decimal("0"),pending)),
            "status":status if pending>0 or month=="2026-02" else "MATCHES_LEDGER"})
    expected=sum(Decimal(row["reported_tenant_paid"]) for row in rows)
    posted=sum((Decimal(row["tenant_paid_already_posted"]) for row in rows if row["month"]!="2026-02"),Decimal("0"))
    Packet.objects.create(
        workspace_id=tenant.workspace_id,tenant_id=tenant.pk,lease_id=prior.lease_id,
        packet_type="ROXANA_2026_OWNER_REPORTED_PAYMENT_REVIEW",
        template_name="Updated owner payment spreadsheet; receipt matching and fee review",
        field_data={
          "source_note":"Owner revised monthly payment spreadsheet on 2026-10-23. March $2706 receipt date(s), method(s), and bank references are not yet supplied; do not invent dates.",
          "period":"2026-02 through 2026-10",
          "status":"PENDING_BANK_RECEIPT_MATCH",
          "monthly_payment_summary":rows,
          "reported_tenant_total_including_former_manager":"8640.00",
          "reported_tenant_total_after_takeover":"8510.00",
          "ledger_tenant_total_after_takeover_at_review":str(posted),
          "missing_receipts_provisional":str(Decimal("8510.00")-posted),
          "tenant_rent_charged_including_february_opening":"12143.00",
          "tenant_rent_outstanding_if_receipts_verified":"3503.00",
          "existing_posted_late_fees":"250.00",
          "tenant_balance_with_posted_fees_if_receipts_verified":"3753.00",
          "max_additional_late_fees_to_review":"550.00",
          "tenant_balance_if_all_unposted_fees_lawful_and_eligible":"4303.00",
          "fee_notice":"No new fees posted. Previous five $50 charges on April–August 2nd predate apparent Adair historic fee timing. Exact signed lease trigger dates and individual March receipts must be checked.",
          "security_deposit_applied":"0.00",
          "deposit_transfer_to_owner_reported":"1485.00",
          "mha_unreceived_from_march_to_september":"767.00",
          "mha_separate_from_tenant":True,
          "formal_tenant_statement_ready":False,
        })
class Migration(migrations.Migration):
    dependencies=[("pm_workspace","0014_reconcile_roxana_2026")]
    operations=[migrations.RunPython(record_owner_report,migrations.RunPython.noop)]
