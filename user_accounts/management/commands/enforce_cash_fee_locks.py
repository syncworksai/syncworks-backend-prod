# backend/user_accounts/management/commands/enforce_cash_fee_locks.py
from __future__ import annotations

from django.core.management.base import BaseCommand

from user_accounts.services.cash_fee_locks import enforce_overdue_cash_fee_locks


class Command(BaseCommand):
    help = "Lock businesses that have overdue CASH_FEE invoices (1 missed payment)."

    def handle(self, *args, **options):
        res = enforce_overdue_cash_fee_locks()
        self.stdout.write(self.style.SUCCESS(
            f"Done. overdue_found={res.overdue_found} businesses_locked={res.businesses_locked} "
            f"skipped_exempt={res.businesses_skipped_exempt}"
        ))