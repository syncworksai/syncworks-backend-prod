from django.core.management.base import BaseCommand

from sync_ai.assistant_reminders import process_departure_reminders


class Command(BaseCommand):
    help = "Process proactive SYNC Assistant reminder jobs."

    def handle(self, *args, **options):
        result = process_departure_reminders()
        self.stdout.write(self.style.SUCCESS(f"SYNC proactive reminders: {result}"))
