from django.core.management.base import BaseCommand

from personal_calendar.sync_runner import sync_due_connections
from sync_ai.assistant_reminders import process_departure_reminders


class Command(BaseCommand):
    help = "Run due calendar connection syncs and SYNC Assistant departure reminders."

    def handle(self, *args, **options):
        payload = {
            "calendar_sync": sync_due_connections(),
            "departure_reminders": process_departure_reminders(),
        }
        self.stdout.write(str(payload))
