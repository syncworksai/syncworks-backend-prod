from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from user_accounts.management.commands.seed_syncworks_demo import BUSINESS_NAME, EMAILS
from user_accounts.models import Business


class DemoClassificationTests(TestCase):
    def setUp(self):
        call_command("seed_syncworks_demo", stdout=StringIO())

    def test_demo_business_is_free_and_excluded_from_kpis(self):
        business = Business.objects.get(name=BUSINESS_NAME)
        self.assertTrue(business.is_demo)
        self.assertTrue(business.exclude_from_kpis)
        self.assertTrue(business.is_billing_exempt_now())
        self.assertTrue(business.is_subscriptions_exempt_now())

    def test_demo_users_never_receive_platform_privileges(self):
        User = get_user_model()
        user_fields = {field.name for field in User._meta.get_fields()}
        for user in User.objects.filter(email__in=EMAILS.values()):
            self.assertFalse(user.is_superuser)
            self.assertFalse(user.is_staff)
            if "is_platform_admin" in user_fields:
                self.assertFalse(user.is_platform_admin)

    def test_validator_passes_for_valid_demo_workspace(self):
        output = StringIO()
        call_command("validate_syncworks_demo", stdout=output)
        self.assertIn("validation passed", output.getvalue())

    def test_validator_fails_if_kpi_exclusion_is_removed(self):
        business = Business.objects.get(name=BUSINESS_NAME)
        business.exclude_from_kpis = False
        business.save(update_fields=["exclude_from_kpis"])
        with self.assertRaises(CommandError):
            call_command("validate_syncworks_demo", stdout=StringIO(), stderr=StringIO())

    def test_real_business_defaults_to_production_classification(self):
        User = get_user_model()
        owner = User.objects.create_user(username="production-owner", email="production.owner@example.com", password="safe-password")
        business = Business.objects.create(owner=owner, name="Production Services LLC")
        self.assertFalse(business.is_demo)
        self.assertFalse(business.exclude_from_kpis)
