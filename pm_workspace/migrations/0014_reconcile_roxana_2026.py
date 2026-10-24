"""Owner-approved, auditable Roxana tenant ledger reconciliation (23 Oct 2026).

Source: 2024-2026 Adair tenant & owner statements, owner's March 1 takeover,
MHA 2026 correspondence (August full tenant rent; September $377 HAP;
October HAP abated), and SyncWorks payment history.

CRITICAL: no SECURITY_DEPOSIT or PAYMENT row is created/edited. No automatic
historical late fees. This migration intentionally targets exactly one existing
record and refuses to apply if financial rows changed after owner review.
"""
from datetime import date
from decimal import Decimal
from django.db import migrations, transaction
from django.db.models import Sum

D=Decimal
RENTS=("RENT","RENT_TENANT","RENT_HOUSING")
START=date(2026,3,1)
END=date(2026,10,31)
RATES={
    "2026-03":(D("1407.00"),D("78.00"),D("0.00")),
    "2026-04":(D("1407.00"),D("78.00"),D("0.00")),
    "2026-05":(D("1407.00"),D("78.00"),D("0.00")),
    "2026-06":(D("1407.00"),D("78.00"),D("0.00")),
    "2026-07":(D("1407.00"),D("78.00"),D("0.00")),
    "2026-08":(D("1485.00"),D("0.00"),D("0.00")),
    "2026-09":(D("1108.00"),D("377.00"),D("0.00")),
    "2026-10":(D("1108.00"),D("0.00"),D("377.00")),
}
BASELINE={
 "2026-03":(D("1400"),D("0")),
 "2026-04":(D("1400"),D("0")),
 "2026-05":(D("1407"),D("78")),
 "2026-06":(D("1407"),D("78")),
 "2026-07":(D("1407"),D("78")),
 "2026-08":(D("1407"),D("78")),
 "2026-09":(D("1407"),D("78")),
 "2026-10":(D("1407"),D("78")),
}
REF="OWNER-APPROVED-ROXANA-20261023"

def reconcile(apps,schema_editor):
    Tenant=apps.get_model("pm_workspace","PMTenant")
    Lease=apps.get_model("pm_workspace","PMLease")
    Ledger=apps.get_model("pm_workspace","PMLedgerEntry")
    Packet=apps.get_model("pm_workspace","PMDocumentPacket")
    Workspace=apps.get_model("pm_workspace","PMWorkspace")

    workspaces=list(Workspace.objects.filter(name__iexact="Lord Holdings").values_list("id",flat=True))
    if len(workspaces)!=1:return
    ws_id=workspaces[0]
    tenants=list(Tenant.objects.select_for_update().filter(
        workspace_id=ws_id,first_name__iexact="Tonya",last_name__iexact="English",
        property_name__iexact="Roxana"))
    if len(tenants)!=1:return
    tenant=tenants[0]
    # Migration is deliberately single-application, including environments
    # running the same migration file again during disaster recovery.
    if Ledger.objects.filter(tenant_id=tenant.id,reference=REF+"-OPENING").exists():
        return
    if Packet.objects.filter(tenant_id=tenant.id,packet_type="ROXANA_2026_OWNER_APPROVED_RECONCILIATION").exists():
        return
    lease=Lease.objects.select_for_update().filter(
        workspace_id=ws_id,tenant_id=tenant.id,status="ACTIVE").order_by("-start_date","-id").first()
    if not lease:
        raise RuntimeError("Roxana reconciliation halted: active source lease missing.")

    records=list(Ledger.objects.select_for_update().filter(
        workspace_id=ws_id,tenant_id=tenant.id,entry_date__gte=START,entry_date__lte=END))
    if len(records)!=32:
        raise RuntimeError("Roxana reconciliation halted: source ledger changed; expected 32 March-Oct entries.")
    payments=sum((r.amount for r in records if r.entry_type=="PAYMENT"
                 and (r.category!="RENT_HOUSING" and r.payment_method!="HOUSING_AUTHORITY")),D("0"))
    housing_received=sum((r.amount for r in records if r.entry_type=="PAYMENT"
                 and (r.category=="RENT_HOUSING" or r.payment_method=="HOUSING_AUTHORITY")),D("0"))
    fees=sum((r.amount if r.entry_type in ("CHARGE","ADJUSTMENT") else -r.amount
             for r in records if r.category=="LATE_FEE"),D("0"))
    escrow=[r for r in records if r.category.strip().upper().replace(" ","_")=="SECURITY_DEPOSIT"]
    if payments!=D("5804.00") or housing_received!=0 or fees!=D("250.00") or len(escrow)!=1 or escrow[0].amount!=D("1500"):
        raise RuntimeError("Roxana reconciliation halted: receipts, fees or old deposit row no longer match source review.")
    old={}
    for month in RATES:
        rows=[r for r in records if r.entry_date.strftime("%Y-%m")==month]
        tenant_amt=sum((r.amount if r.entry_type in ("CHARGE","ADJUSTMENT") else -r.amount
                 for r in rows if r.category in ("RENT","RENT_TENANT") and r.entry_type!="PAYMENT"),D("0"))
        housing_amt=sum((r.amount if r.entry_type in ("CHARGE","ADJUSTMENT") else -r.amount
                 for r in rows if r.category=="RENT_HOUSING" and r.entry_type!="PAYMENT"),D("0"))
        old[month]=(tenant_amt,housing_amt)
    if old!=BASELINE:
        raise RuntimeError("Roxana reconciliation halted: monthly charges were edited; preview a fresh reconciliation.")

    # This is an opening arrears carryover, not a duplicate $1,485 February
    # invoice. Feb received $78 HAP + $130 tenant; $1,277 unpaid.
    # Dated 28 Feb so the FIFO algorithm prioritizes it before March's rent.
    opening=Ledger.objects.create(
        workspace_id=ws_id,tenant_id=tenant.id,lease_id=lease.id,
        entry_date=date(2026,2,28),entry_type="CHARGE",
        category="RENT_TENANT",amount=D("1277.00"),
        reference=REF+"-OPENING",
        memo="Opening tenant rent arrears as of 2026-03-01; Feb contract $1,485 less $78 MHA received by former PM and $130 tenant paid to former PM. TenantCloud showed only $208 as February amount due. No deposit applied. Provisional pending direct February receipts or earlier-arrears review.")

    changes=[]
    for month,(wanted_t,wanted_h,abated) in RATES.items():
        current_t,current_h=old[month]
        for payer,category,difference in (
            ("TENANT","RENT_TENANT",wanted_t-current_t),
            ("HOUSING","RENT_HOUSING",wanted_h-current_h)):
            if difference==0:continue
            ref=f"RECON-{tenant.id}-{month}-{payer}-OWNERAPPROVED20261023"
            if Ledger.objects.filter(tenant_id=tenant.id,reference=ref).exists():
                raise RuntimeError("Roxana reconciliation halted: adjustment reference already exists.")
            day=date.fromisoformat(month+"-01")
            item=Ledger.objects.create(
                workspace_id=ws_id,tenant_id=tenant.id,lease_id=lease.id,
                entry_date=day,entry_type="CHARGE" if difference>0 else "CREDIT",
                category=category,amount=abs(difference),reference=ref,
                memo=("Owner-reviewed correction to $1,485/month contracted rent, "
                      f"{month}: tenant {wanted_t}, HAP billable {wanted_h}. "
                      + ("October $377 housing share ABATED, not billed to tenant or marked received. " if abated else "")
                      + "Existing receipts, previously posted late fees and deposit history unchanged."
                      ))
            changes.append({"entry_id":item.pk,"month":month,"payer":payer,
                            "delta":str(difference),"reference":ref})

    # Correct the one active lease's financial setup only, not its
    # previously entered legal dates or unsigned renewals.
    before={"monthly_rent":str(lease.monthly_rent),
            "tenant_portion":str(lease.tenant_portion),
            "assistance_portion":str(lease.assistance_portion),
            "end_date":str(lease.end_date)}
    lease.monthly_rent=D("1485")
    lease.tenant_portion=D("1108")
    lease.assistance_portion=D("377")
    lease.section8=True
    lease.save(update_fields=["monthly_rent","tenant_portion","assistance_portion","section8","updated_at"])
    tenant.monthly_rent=D("1485")
    tenant.save(update_fields=["monthly_rent","updated_at"])
    source=("Adair TenantCloud tenant and owner statements dated Oct 23 2026; "
            "Adair email confirming $208 February received; user-confirmed USAA "
            "and direct tenant payments; MHA written monthly allocations and October abatement.")
    Packet.objects.create(
        workspace_id=ws_id,tenant_id=tenant.id,lease_id=lease.id,
        packet_type="ROXANA_2026_OWNER_APPROVED_RECONCILIATION",
        template_name="Owner-approved March 2026 takeover rent reconciliation",
        field_data={
            "review_date":"2026-10-23","effective_as_of":"2026-10-23",
            "status":"POSTED_PROVISIONAL_RECONCILIATION",
            "source_note":source,
            "lease_previous":before,
            "lease_current":{"monthly_rent":"1485.00","tenant_portion":"1108.00",
                             "housing_portion":"377.00",
                             "lease_end_date_unchanged":str(lease.end_date)},
            "opening_arrears":{"period":"2026-02","opening_date":"2026-03-01",
                               "contract_rent":"1485.00","former_manager_hap_received":"78.00",
                               "former_manager_tenant_received":"130.00",
                               "tenant_opening_owed":"1277.00",
                               "entry_id":opening.pk,"conditional":True},
            "months":[{"period":month,"contract_rent":"1485.00",
                       "tenant_charge":str(val[0]),"housing_billable":str(val[1]),
                       "housing_abated":str(val[2])} for month,val in RATES.items()],
            "adjustment_entries":changes,"existing_tenant_receipts_preserved":"5804.00",
            "existing_late_fees_preserved":"250.00","new_receipts_created":0,
            "new_late_fees_created":0,
            "security_deposit":{"paperwork_proposed":"1500.00",
                                "reported_transfer_to_owner":"1485.00",
                                "applied_to_rent":"0.00",
                                "status":"SEPARATE_ESCROW_ACCOUNT_RECONCILIATION"},
            "review_flags":["April 6 $704 direct payment must be bank-verified",
                            "February other direct receipts unknown",
                            "late-fee dates and lease terms require review",
                            "Jan 2026 and earlier arrears provisionally assumed satisfied",
                            "MHA reversal to former manager unresolved",
                            "2025 recorded lease end date not changed without renewal documents"]
        })

    Packet.objects.create(
        workspace_id=ws_id,tenant_id=tenant.id,lease_id=lease.id,
        packet_type="TENANT_EXTERNAL_PAYMENT_RECONCILIATION",
        template_name="MHA 2026 housing payment evidence",
        field_data={"records":[
            {"id":f"roxana-mha-{month}","period":month,"amount":"78.00",
             "category":"HAP_PAID_TO_FORMER_MANAGER","evidence_status":"DISPUTED",
             "note":"MHA reports paid to Adair; Adair asserts bank withdrawal/reversal should have occurred. Neither reverse nor transfer confirmed."}
             for month in ("2026-03","2026-04","2026-05","2026-06")
         ]+[
             {"id":"roxana-mha-2026-07","period":"2026-07","amount":"78.00",
              "category":"HAP_ON_HOLD","evidence_status":"REPORTED",
              "note":"MHA states payable after transfer paperwork is processed; not received by owner."},
             {"id":"roxana-mha-2026-09","period":"2026-09","amount":"377.00",
              "category":"HAP_ON_HOLD","evidence_status":"REPORTED",
              "note":"MHA states payable after transfer paperwork is processed; not received by owner."},
             {"id":"roxana-mha-2026-10","period":"2026-10","amount":"377.00",
              "category":"OTHER_UNVERIFIED","evidence_status":"DOCUMENTED",
              "note":"HAP abated for October inspection issue. Not a collectible tenant bill or recorded MHA receipt."}
        ],"source_note":"MHA email Oct 2026; separately reported Adair statement."})
    Packet.objects.create(
        workspace_id=ws_id,tenant_id=tenant.id,lease_id=lease.id,
        packet_type="TENANT_DEPOSIT_TRANSFER_REVIEW",
        template_name="Security deposit evidence: original vs former-manager transfer",
        field_data={"paperwork_amount":"1500.00",
                    "reported_transfer_amount":"1485.00","status":"NEEDS_REVIEW",
                    "rent_credit_applied":False,
                    "description":"2024 paperwork proposes $1,500. Adair confirms $1,485 transferred February 12, 2026; owner bank shows corresponding February 13 deposit. Amount difference $15 requires confirmation; no deposit applied to rent.",
                    "source_note":"2024 onboarding documents, Adair October 2026 email, owner USAA Feb 13 deposit."})
    months=[{"month":m,"rent":"1485.00","mha":str(H if m!="2026-10" else D("377")),
             "tenant":str(T),"source_status":("FORMER_MANAGER" if m=="2026-02" else
               "ABATED_NOT_RECEIVABLE" if m=="2026-10" else "MHA_DOCUMENTED")}
            for m,(T,H,_abate) in [
                ("2026-02",(D("1407"),D("78"),D("0"))),
                *RATES.items()
            ]]
    Packet.objects.create(
        workspace_id=ws_id,tenant_id=tenant.id,lease_id=lease.id,
        packet_type="PM_SIMPLE_MONTHLY_RENT_SCHEDULE",
        template_name="Owner-approved simple monthly rent schedule",
        field_data={"months":months,"source_note":source,
                    "status":"RECONCILED_POSTED","notice":"October MHA $377 is abated; Feb $1,277 is opening arrears only."})


class Migration(migrations.Migration):
    dependencies=[("pm_workspace","0013_pm_tenant_property")]
    operations=[migrations.RunPython(reconcile,migrations.RunPython.noop)]
