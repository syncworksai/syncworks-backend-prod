# backend/user_accounts/management/commands/generate_cash_fee_invoices.py
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from user_accounts.services.cash_fee_billing import generate_monthly_cash_fee_invoices


class Command(BaseCommand):
    help = "Generate monthly CashFeeInvoice rows for previous month cash-confirmed tickets."

    def add_arguments(self, parser):
        parser.add_argument("--fee-bps", type=int, default=100, help="Fee in basis points (default 100 = 1%).")
        parser.add_argument("--due-days", type=int, default=7, help="Due date offset in days from today (default 7).")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run inside a transaction and rollback (no writes).",
        )

    def handle(self, *args, **options):
        fee_bps = int(options.get("fee_bps") or 100)
        due_days = int(options.get("due_days") or 7)
        dry_run = bool(options.get("dry_run"))

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN enabled: will rollback changes."))

        with transaction.atomic():
            res = generate_monthly_cash_fee_invoices(fee_bps=fee_bps, due_days=due_days)

            self.stdout.write(self.style.SUCCESS("Cash fee invoice generation complete."))
            self.stdout.write(f"businesses_considered={res.businesses_considered}")
            self.stdout.write(f"businesses_skipped_exempt={res.businesses_skipped_exempt}")
            self.stdout.write(f"invoices_created={res.invoices_created}")
            self.stdout.write(f"invoices_skipped_zero={res.invoices_skipped_zero}")
            self.stdout.write(f"invoices_skipped_existing={res.invoices_skipped_existing}")

            if dry_run:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Rolled back (dry run)."))