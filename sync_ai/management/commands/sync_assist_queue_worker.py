"""Run bounded Sync Assist jobs from an independent scheduler or worker service."""
import os
from django.core.management.base import BaseCommand, CommandError
from sync_ai.assist_job_queue import run_batch


class Command(BaseCommand):
    help = "Run queued, owner-authorized internal Sync Assist tasks; no outbound actions."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process up to --max-jobs and exit.")
        parser.add_argument("--max-jobs", type=int, default=5)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        limit = options["max_jobs"]
        if not 1 <= limit <= 20:
            raise CommandError("--max-jobs must be 1 to 20")
        if options["dry_run"]:
            from user_accounts.models import SyncAssistJob
            from django.utils import timezone
            count = SyncAssistJob.objects.filter(
                state__in=["QUEUED", "RETRY"], next_run_at__lte=timezone.now()
            ).count()
            self.stdout.write(f"Eligible persisted jobs: {count}. No execution occurred.")
            return
        if os.environ.get("SYNC_ASSIST_DURABLE_WORKER_ENABLED") != "true":
            raise CommandError("Durable worker is disabled; explicit deployment opt-in required.")
        if not options["once"]:
            raise CommandError("Use --once with an independently configured scheduler. This command never runs a hidden loop.")
        results = run_batch(limit=limit)
        self.stdout.write(f"Processed {len(results)} job(s): {results}")
