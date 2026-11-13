import os

from django.core.management.base import BaseCommand, CommandError
from sync_ai.assist_discovery import discover_pilot_tasks


class Command(BaseCommand):
    help = "Read-only Sync Assist private-pilot scan; scheduled execution requires explicit opt-in."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Inspect candidates without recording tasks.")
        parser.add_argument("--scheduled", action="store_true", help="Run from configured external scheduler (requires opt-in).")

    def handle(self, *args, **options):
        scheduled = bool(options["scheduled"])
        if scheduled and os.environ.get("SYNC_ASSIST_SCHEDULED_SCAN_ENABLED") != "true":
            raise CommandError(
                "Scheduled Sync Assist scanning is disabled. Configure the private job "
                "and set SYNC_ASSIST_SCHEDULED_SCAN_ENABLED=true on that job only."
            )
        result = discover_pilot_tasks(
            dry_run=bool(options["dry_run"]),
            run_source="scheduled" if scheduled else "manual",
        )
        self.stdout.write(str(result))
