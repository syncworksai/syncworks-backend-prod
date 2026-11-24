"""Run synthetic-only freelance work in an independently scheduled process."""
import os
from uuid import UUID
from django.core.management.base import BaseCommand, CommandError
from sync_ai.freelance_synthetic_queue import run_batch

class Command(BaseCommand):
    help = "Run bounded synthetic freelance CSV tasks (never actual client files)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--max-jobs", type=int, default=1)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--job-id", type=str, default=None, help="Only claim this one synthetic job UUID.")

    def handle(self, *args, **options):
        if not 1 <= options["max_jobs"] <= 5:
            raise CommandError("--max-jobs must be between 1 and 5.")
        if options["dry_run"]:
            from user_accounts.models import FreelanceSyntheticJob
            count = FreelanceSyntheticJob.objects.filter(state="QUEUED").count()
            self.stdout.write(f"Synthetic queued jobs: {count}. No work executed.")
            return
        if not options["once"] or os.getenv("FREELANCE_SYNTHETIC_WORKER_ENABLED") != "true":
            raise CommandError("Explicit --once and FREELANCE_SYNTHETIC_WORKER_ENABLED=true required.")
        job_id = None
        if options["job_id"]:
            try:
                job_id = UUID(options["job_id"])
            except (ValueError, TypeError, AttributeError):
                raise CommandError("Invalid synthetic job UUID.")
            if options["max_jobs"] != 1:
                raise CommandError("Targeted job runs must use max-jobs=1.")
        self.stdout.write(f"Processed: {run_batch(limit=options['max_jobs'], target_job_id=job_id)}")
