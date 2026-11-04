"""No-network tests for PM lead subscription math, permissions and event activation."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from pm_workspace.lead_billing_service import bundle_discount, is_founder, price_quote, has_capture_entitlement
from pm_workspace.lead_billing_views import _apply_subscription_event
from pm_workspace.models import PMWorkspace, PMLeadSubscription
from user_accounts.models.user_billing import UserBillingProfile

User = get_user_model()


class PMLeadPricingTests(TestCase):
    def test_volume_discounts_and_cents_rounding(self):
        assert price_quote(1)["monthly_cents"] == 999
        assert price_quote(2)["monthly_cents"] == 1998
        assert price_quote(3)["monthly_cents"] == 2697
        assert price_quote(5)["monthly_cents"] == 4246
        assert price_quote(8)["monthly_cents"] == 6394
        assert bundle_discount(2) == 0
        assert bundle_discount(3) == 10
        assert bundle_discount(5) == 15
        assert bundle_discount(8) == 20
        for value in (-1, 0, 101, 1.5, "3"):
            with self.assertRaises(ValueError):
                price_quote(value)


class PMLeadBillingTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="pm-billing-owner", email="pm-billing-owner@example.org", password="pw"
        )
        self.other = User.objects.create_user(
            username="pm-billing-other", email="pm-billing-other@example.org", password="pw"
        )
        self.workspace = PMWorkspace.objects.create(owner=self.owner, name="Billing Test Workspace")
        self.headers = {"HTTP_X_PM_WORKSPACE_ID": str(self.workspace.id)}
        self.client.force_authenticate(self.owner)

    def test_free_manual_leads_without_checkout(self):
        r = self.client.get("/api/v1/pm-hub/lead-addons/status/", **self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["subscription_active"])
        self.assertEqual(r.data["mailbox_limit"], 0)
        self.assertFalse(r.data["catalog"]["ai_extraction"]["available"])
        with patch.dict("os.environ", {"STRIPE_PM_LEAD_CHECKOUT_ENABLED": "false"}):
            checkout = self.client.post("/api/v1/pm-hub/lead-addons/checkout/", {"mailboxes": 2},
                                        format="json", **self.headers)
        self.assertEqual(checkout.status_code, 503)
        self.assertFalse(PMLeadSubscription.objects.exists())

    def test_workspace_scoping(self):
        self.client.force_authenticate(self.other)
        r = self.client.get("/api/v1/pm-hub/lead-addons/status/", **self.headers)
        self.assertEqual(r.status_code, 403)

    def test_verified_founder_is_unlimited_with_no_stripe_calls(self):
        user = User.objects.create_user(
            username="founder-billing-test", email="jacoblord7@outlook.com", password="pw",
            email_verified=True,
        )
        UserBillingProfile.objects.create(user=user, beta_subscriptions_waived=True)
        pm = PMWorkspace.objects.create(owner=user, name="Founder Test Workspace")
        self.client.force_authenticate(user)
        hdr = {"HTTP_X_PM_WORKSPACE_ID": str(pm.id)}
        r = self.client.get("/api/v1/pm-hub/lead-addons/status/", **hdr)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["founder_access"])
        self.assertIsNone(r.data["mailbox_limit"])
        self.assertEqual(len(r.data["enabled_features"]), len(r.data["catalog"]))
        checkout = self.client.post("/api/v1/pm-hub/lead-addons/checkout/",
                                    {"mailboxes": 100}, format="json", **hdr)
        self.assertEqual(checkout.status_code, 200)
        self.assertTrue(checkout.data["founder_access"])
        self.assertFalse(PMLeadSubscription.objects.filter(workspace=pm).exists())

    def test_signed_subscription_events_control_paid_access(self):
        row = PMLeadSubscription.objects.create(
            workspace=self.workspace, status="PENDING", stripe_customer_id="cus_sandbox",
            stripe_subscription_id="", mailbox_count=3, features=["inbox_capture"],
            monthly_cents=2697,
        )
        self.assertFalse(has_capture_entitlement(self.workspace))
        payload = {
            "id": "sub_sandbox", "customer": "cus_sandbox", "status": "active",
            "metadata": {"syncworks_scope": "pm_lead_capture",
                         "workspace_id": str(self.workspace.id)},
            "cancel_at_period_end": False,
            "current_period_end": int(datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp()),
        }
        self.assertTrue(_apply_subscription_event(payload, "customer.subscription.updated"))
        row.refresh_from_db()
        self.assertEqual(row.status, "ACTIVE")
        self.assertTrue(has_capture_entitlement(self.workspace))
        self.assertTrue(_apply_subscription_event(payload, "customer.subscription.deleted"))
        row.refresh_from_db()
        self.assertEqual(row.status, "CANCELED")
        self.assertFalse(has_capture_entitlement(self.workspace))

    def test_second_customer_cannot_hijack_workspace_billing(self):
        PMLeadSubscription.objects.create(workspace=self.workspace, status="PENDING",
                                          stripe_customer_id="cus_owner")
        payload = {"id": "sub_bad", "customer": "cus_else", "status": "active",
                   "metadata": {"syncworks_scope": "pm_lead_capture",
                                "workspace_id": str(self.workspace.id)}}
        with self.assertRaises(ValueError):
            _apply_subscription_event(payload, "customer.subscription.created")
