from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

from platform_affiliates.services.commission_service import (
    record_user_health_subscription_commission,
)


class Command(BaseCommand):
    help = "Record a Health subscription commission for a user referred by an affiliate."

    def add_arguments(self, parser):
        parser.add_argument("--user-email", required=True)
        parser.add_argument("--amount", required=True, help="Net SyncWorks revenue amount, e.g. 2.99")
        parser.add_argument("--source-reference", required=True, help="Unique source reference, e.g. stripe session/payment id")
        parser.add_argument("--gross-amount", default="0.00")
        parser.add_argument("--source-date", default="")
        parser.add_argument("--memo", default="")
        parser.add_argument("--ai", action="store_true", help="Use Health AI Subscription revenue source")

    def handle(self, *args, **options):
        User = get_user_model()

        email = str(options["user_email"] or "").strip().lower()
        user = User.objects.filter(email__iexact=email).select_related("referred_by_affiliate").first()

        if not user:
            raise CommandError(f"User not found: {email}")

        if not getattr(user, "referred_by_affiliate_id", None):
            self.stdout.write(
                self.style.WARNING(
                    f"No commission created. User {email} does not have an affiliate attribution."
                )
            )
            return

        source_date = None
        raw_source_date = str(options.get("source_date") or "").strip()

        if raw_source_date:
            source_date = parse_date(raw_source_date)
            if not source_date:
                raise CommandError("source-date must be YYYY-MM-DD")

        commission = record_user_health_subscription_commission(
            user=user,
            net_syncworks_revenue_amount=options["amount"],
            gross_revenue_amount=options["gross_amount"],
            source_reference=options["source_reference"],
            source_date=source_date,
            memo=options["memo"],
            health_ai=bool(options["ai"]),
        )

        if not commission:
            self.stdout.write(
                self.style.WARNING(
                    f"No commission created for {email}."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                "Health affiliate commission recorded: "
                f"id={commission.id} "
                f"affiliate={commission.affiliate.code} "
                f"source={commission.revenue_source} "
                f"commission=${commission.commission_amount}"
            )
        )