"""Opt-in bounded Sync Assist private-pilot internal worker.

Intended for an external scheduler. No schedule is installed by this code.
Only one non-network internal action per invocation; no email or external writes.
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from sync_ai.assist_pilot_views import PILOT_EMAIL
from sync_ai.assist_workday_views import _snapshot
from sync_ai.assist_workday_execution import execute_one


class Command(BaseCommand):
    help = "Execute one eligible internal workday step, when explicitly enabled for the pilot."

    def add_arguments(self, parser):
        parser.add_argument("--goal-id", help="Run only the specified goal UUID.")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--scheduled", action="store_true")

    def handle(self, *args, **options):
        if options["scheduled"] and os.environ.get("SYNC_ASSIST_WORKDAY_SCHEDULER_ENABLED") != "true":
            raise CommandError("Scheduled workday execution disabled. Explicit pilot opt-in required.")
        if not options["dry_run"] and os.environ.get("SYNC_ASSIST_WORKDAY_INTERNAL_EXECUTION_ENABLED") != "true":
            raise CommandError("Internal execution disabled. Enable the pilot worker explicitly.")
        user = get_user_model().objects.filter(email__iexact=PILOT_EMAIL, is_active=True).first()
        if not user:
            raise CommandError("Pilot account not found.")
        goal_id = options.get("goal_id")
        goals = _snapshot(user)["goals"]
        if goal_id:
            goals = [g for g in goals if g["id"] == goal_id]
            if not goals:
                raise CommandError("Pilot goal not found.")
        for goal in goals:
            eligible = any(step["status"] in {"PLANNED", "BLOCKED"} and
                           step["role"] in {"RESEARCH_ANALYST", "SALES_MANAGER", "CHIEF_OF_STAFF"}
                           for step in goal["steps"])
            if not eligible:
                continue
            if options["dry_run"]:
                self.stdout.write(f"Eligible for internal work: {goal['id']}")
                return
            outcome = execute_one(user, goal["id"])
            self.stdout.write(f"Goal {goal['id']}: {outcome['code']}")
            return
        self.stdout.write("No eligible internal work. Awaiting approvals or new tasks.")
