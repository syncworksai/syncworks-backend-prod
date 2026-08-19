from django.core.management.base import BaseCommand

from sync_ai.assistant_reminders import process_departure_reminders
from sync_ai.notification_engine import process_sync_notifications


class Command(BaseCommand):
    help = "Process proactive SYNC Assistant notifications, emails, and departure reminders."

    def add_arguments(self, parser):
        parser.add_argument("--user-limit", type=int, default=500)

    def handle(self, *args, **options):
        notification_result = process_sync_notifications(user_limit=options["user_limit"])
        departure_result = process_departure_reminders()
        self.stdout.write(self.style.SUCCESS(
            f"SYNC notifications: {notification_result} | departures: {departure_result}"
        ))
