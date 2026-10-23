"""Daily idempotent lease billing. Must be scheduled on Render after deployment.

Only leases with an explicitly activated setup are eligible. Current-month
rent is billed on/after due date. Historic backfill requires owner review
through the lease-builder page. Late fee automation starts no earlier than the
verified auto_late_fee_from, never retroactively.
"""
from datetime import date
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from pm_workspace.models import PMTenant, PMLease, PMLedgerEntry
from pm_workspace.lease_billing_engine import (
    PACKET, apply_rent, get_setup, late_fee_preview,
)

class Command(BaseCommand):
    help="Post first-of-month lease rent for activated tenants; optionally post verified future late fees."

    def add_arguments(self,parser):
        parser.add_argument("--dry-run",action="store_true",
            help="List eligible ledger charges without creating them.")
        parser.add_argument("--as-of",default="",
            help="Local date YYYY-MM-DD, for testing only.")

    def handle(self,*args,**options):
        today=date.fromisoformat(options["as_of"]) if options["as_of"] else timezone.localdate()
        target_month=today.strftime("%Y-%m")
        active=PMTenant.objects.filter(
            document_packets__packet_type=PACKET,
            document_packets__field_data__active=True,
            workspace__is_active=True).distinct().values_list("id",flat=True)
        posted=0
        fees=0
        skipped=0
        for tenant_id in active.iterator():
            with transaction.atomic():
                tenant=PMTenant.objects.select_for_update().filter(pk=tenant_id,workspace__is_active=True).first()
                if tenant is None:continue
                lease=tenant.leases.exclude(status="ENDED").order_by("-start_date","-id").first()
                if not lease:
                    skipped+=1
                    continue
                packet,config=get_setup(tenant)
                if not packet or not config.get("active"):
                    continue
                # Do not bill the month if the lease terminates without rollover.
                if lease.end_date and today>lease.end_date and not lease.converts_to_month_to_month:
                    skipped+=1
                    continue
                if not options["dry_run"]:
                    _,new=apply_rent(tenant,lease,config,today,only_month=target_month)
                    posted+=len(new)
                else:
                    from pm_workspace.lease_billing_engine import preview_rows
                    preview=[x for x in preview_rows(tenant,lease,config,today)
                        if x["month"]==target_month and not x["blocked"]]
                    posted+=sum(bool(Decimal(x[k])) for x in preview for k in ("adjust_tenant","adjust_housing"))
                if not config.get("auto_late_fees") or not config.get("late_fee_verified"):
                    continue
                since=date.fromisoformat(config.get("auto_late_fee_from") or str(today))
                candidates=[x for x in late_fee_preview(tenant,lease,config,today)
                    if x["month"]==target_month and date.fromisoformat(x["date"])>=since]
                for item in candidates:
                    if Decimal(item["amount"])<=0:continue
                    if options["dry_run"]:
                        fees+=1
                        continue
                    # Locking tenant row + deterministic reference prevents reruns.
                    ref=f"LEASE-AUTO-LATE-{tenant.id}-{item['month']}"
                    if tenant.ledger_entries.filter(reference=ref).exists():continue
                    PMLedgerEntry.objects.create(
                        workspace=tenant.workspace,tenant=tenant,lease=lease,
                        entry_date=date.fromisoformat(item["date"]),
                        entry_type="CHARGE",category="LATE_FEE",amount=Decimal(item["amount"]),
                        reference=ref,memo="Verified lease late fee after grace period; tenant rent was unpaid.",
                    )
                    fees+=1
        self.stdout.write(f"PM lease billing: rent adjustments {posted}, late fees {fees}, skipped {skipped}, dry_run={bool(options['dry_run'])}.")
