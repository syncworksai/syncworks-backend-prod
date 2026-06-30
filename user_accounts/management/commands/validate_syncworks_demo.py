from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError

from user_accounts.management.commands.seed_syncworks_demo import BUSINESS_NAME, EMAILS
from user_accounts.models import AutomationRule, Business, BusinessMember, Ticket


class Command(BaseCommand):
    help = "Validate the isolated SyncWorks live demo workspace."

    def handle(self, *args, **options):
        User = get_user_model()
        errors = []
        users = {user.email: user for user in User.objects.filter(email__in=EMAILS.values())}

        missing = sorted(set(EMAILS.values()) - set(users))
        if missing:
            errors.append(f"Missing demo users: {', '.join(missing)}")

        businesses = Business.objects.filter(name=BUSINESS_NAME)
        if businesses.count() != 1:
            errors.append(f"Expected exactly one demo business; found {businesses.count()}.")
            business = businesses.first()
        else:
            business = businesses.get()

        if business:
            if not business.is_demo:
                errors.append("Demo business is not marked is_demo.")
            if not business.exclude_from_kpis:
                errors.append("Demo business is not excluded from KPIs.")
            if not business.is_billing_exempt_now():
                errors.append("Demo business is not fully billing exempt.")
            if not business.is_subscriptions_exempt_now():
                errors.append("Demo business is not subscription exempt.")

            expected_members = {EMAILS["owner"], EMAILS["dispatch"], EMAILS["tech1"], EMAILS["tech2"]}
            actual_members = set(BusinessMember.objects.filter(business=business, is_active=True).values_list("user__email", flat=True))
            if actual_members != expected_members:
                errors.append(f"Demo membership mismatch. Expected {sorted(expected_members)}, got {sorted(actual_members)}.")

            ticket_count = Ticket.objects.filter(assigned_business=business).count()
            if ticket_count < 8:
                errors.append(f"Expected at least 8 demo tickets; found {ticket_count}.")

            rule_count = AutomationRule.objects.filter(business=business, is_active=True).count()
            if rule_count < 3:
                errors.append(f"Expected at least 3 active demo automation rules; found {rule_count}.")

            leaked = Ticket.objects.filter(assigned_business=business).exclude(customer__email=EMAILS["customer"]).count()
            if leaked:
                errors.append(f"Found {leaked} demo-business tickets owned by non-demo customers.")

        user_fields = {field.name for field in User._meta.get_fields()}
        for email, user in users.items():
            for field in {"is_superuser", "is_staff", "is_platform_admin"} & user_fields:
                if bool(getattr(user, field, False)):
                    errors.append(f"{email} unexpectedly has {field}=True.")

        mislabeled = Business.objects.exclude(name=BUSINESS_NAME).filter(is_demo=True).count()
        if mislabeled:
            errors.append(f"Found {mislabeled} non-demo-name businesses marked as demo.")

        if errors:
            for error in errors:
                self.stderr.write(self.style.ERROR(f"FAIL: {error}"))
            raise CommandError(f"SyncWorks demo validation failed with {len(errors)} issue(s).")

        self.stdout.write(self.style.SUCCESS("SyncWorks live demo validation passed."))
        self.stdout.write(f"Demo users: {len(users)}")
        self.stdout.write(f"Business: {BUSINESS_NAME} (ID {business.id})")
        self.stdout.write(f"Tickets: {Ticket.objects.filter(assigned_business=business).count()}")
        self.stdout.write("KPI classification: DEMO / EXCLUDED")
        self.stdout.write("Billing classification: FULLY EXEMPT / SUBSCRIPTIONS EXEMPT")
        self.stdout.write("God Mode exposure: NONE")
