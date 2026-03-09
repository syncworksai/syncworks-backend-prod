# backend/user_accounts/management/commands/mark_cash_fee_overdue.py
from __future__ import annotations

from django.core.management.base import BaseCommand

from user_accounts.services.cash_fee_billing import mark_overdue_cash_fee_invoices


class Command(BaseCommand):
    help = "Mark CashFeeInvoice rows as OVERDUE when due_date has passed."

    def handle(self, *args, **options):
        updated = mark_overdue_cash_fee_invoices()
        self.stdout.write(self.style.SUCCESS(f"Updated {updated} cash fee invoices to OVERDUE."))