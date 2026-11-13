from django.core.management.base import BaseCommand
from sync_ai.assist_discovery import discover_pilot_tasks


class Command(BaseCommand):
    help = "Run one read-only Sync Assist private-pilot scan (no customer messages or financial actions)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Inspect candidates without recording tasks.")

    def handle(self, *args, **options):
        result = discover_pilot_tasks(dry_run=options["dry_run"])
        self.stdout.write(str(result))
