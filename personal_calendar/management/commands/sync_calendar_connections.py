from django.core.management.base import BaseCommand
from personal_calendar.sync_runner import sync_due_connections


class Command(BaseCommand):
    help = "Run due calendar connection syncs."

    def handle(self, *args, **options):
        self.stdout.write(str(sync_due_connections()))
