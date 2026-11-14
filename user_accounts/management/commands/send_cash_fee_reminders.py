from django.core.management.base import BaseCommand
from user_accounts.services.cash_fee_reminders import send_cash_fee_reminders

class Command(BaseCommand):
    help = "Remind businesses with unpaid cash platform invoices at most weekly."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        self.stdout.write(str(send_cash_fee_reminders(dry_run=options["dry_run"])))
