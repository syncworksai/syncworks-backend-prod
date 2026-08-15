from django.core.management.base import BaseCommand
from django.db.models import Q

from user_accounts.models import User
from user_accounts.models.personal_finance import FinanceConnection
from user_accounts.services.finance_intelligence import infer_recurring_obligations
from user_accounts.services.plaid_finance import sync_connection


class Command(BaseCommand):
    help = "Refresh connected Personal Finance data and infer recurring obligations."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, default=None, help="Run for one user only.")
        parser.add_argument("--skip-provider-sync", action="store_true", help="Infer recurring obligations without contacting connected providers.")

    def handle(self, *args, **options):
        users = User.objects.filter(
            Q(finance_connections__isnull=False)
            | Q(finance_accounts__isnull=False)
            | Q(finance_transactions__isnull=False)
            | Q(finance_obligations__isnull=False)
            | Q(finance_liabilities__isnull=False)
        ).distinct()

        if options["user_id"]:
            users = users.filter(id=options["user_id"])

        processed = 0
        synced = 0
        sync_errors = 0
        recurring_created = 0
        recurring_updated = 0

        for user in users.iterator():
            processed += 1
            if not options["skip_provider_sync"]:
                connections = FinanceConnection.objects.filter(
                    user=user,
                    status=FinanceConnection.Status.ACTIVE,
                )
                for connection in connections:
                    try:
                        sync_connection(connection)
                        synced += 1
                    except Exception as exc:
                        sync_errors += 1
                        self.stderr.write(
                            self.style.WARNING(
                                f"Finance sync failed for user={user.id} connection={connection.id}: {exc}"
                            )
                        )

            recurring = infer_recurring_obligations(user)
            recurring_created += recurring["created"]
            recurring_updated += recurring["updated"]

        self.stdout.write(
            self.style.SUCCESS(
                "Finance runtime complete: "
                f"users={processed} synced={synced} sync_errors={sync_errors} "
                f"recurring_created={recurring_created} recurring_updated={recurring_updated}"
            )
        )
