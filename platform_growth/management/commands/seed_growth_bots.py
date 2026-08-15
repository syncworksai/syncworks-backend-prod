from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from platform_growth.models import GrowthAutomationRecipe


BOT_RECIPES = [
    {
        "name": "Content Calendar Bot",
        "trigger_type": "SCHEDULED",
        "recipe": {
            "bot_key": "content_calendar",
            "package": "SOCIAL_AUTOMATION",
            "sellable": True,
            "schedule": {"interval_minutes": 1440},
            "template": {
                "title": "Daily business social draft",
                "body": "Share one useful tip, customer win, service highlight, or behind-the-scenes update today.",
            },
        },
        "metadata": {"runtime": "SERVER", "outbound_policy": "APPROVAL_REQUIRED"},
    },
    {
        "name": "Lead Follow-Up Bot",
        "trigger_type": "SCHEDULED",
        "recipe": {
            "bot_key": "lead_follow_up",
            "package": "GROWTH_CRM",
            "sellable": True,
            "schedule": {"interval_minutes": 60},
            "lead_age_hours": 24,
            "max_items_per_run": 10,
        },
        "metadata": {"runtime": "SERVER", "outbound_policy": "APPROVAL_REQUIRED"},
    },
]


class Command(BaseCommand):
    help = "Seed the first sellable SyncWorks Business bot recipes for one account."

    def add_arguments(self, parser):
        parser.add_argument("--user-email", required=True)
        parser.add_argument(
            "--activate",
            action="store_true",
            help="Enable recipes immediately. Outbound actions still require approval.",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        try:
            user = User.objects.get(email__iexact=options["user_email"].strip())
        except User.DoesNotExist as exc:
            raise CommandError("No user found for that email.") from exc

        created_count = 0
        updated_count = 0
        for bot in BOT_RECIPES:
            recipe, created = GrowthAutomationRecipe.objects.update_or_create(
                name=bot["name"],
                created_by=user,
                defaults={
                    "trigger_type": bot["trigger_type"],
                    "recipe": bot["recipe"],
                    "metadata": bot["metadata"],
                    "is_active": bool(options["activate"]),
                },
            )
            created_count += int(created)
            updated_count += int(not created)
            self.stdout.write(
                f"{recipe.name}: {'created' if created else 'updated'}; active={recipe.is_active}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Growth bot seed complete: created={created_count} updated={updated_count}."
            )
        )
