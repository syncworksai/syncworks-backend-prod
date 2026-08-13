from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from user_accounts.models import CustomerSettings, UserBillingProfile


User = get_user_model()


class UserJarvisProductTests(APITestCase):
    def auth(self, email="jarvis@example.com"):
        user = User.objects.create_user(
            username=email.split("@")[0],
            email=email,
            password="test-password-123",
        )
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return user

    def test_profile_requires_authentication(self):
        response = self.client.get("/api/v1/sync-ai/jarvis/profile/")
        self.assertEqual(response.status_code, 401)

    def test_basic_profile_has_marketplace_first(self):
        self.auth()
        response = self.client.get("/api/v1/sync-ai/jarvis/profile/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["plan"], "BASIC")
        self.assertEqual(response.data["module_catalog"][0]["id"], "marketplace")
        self.assertTrue(response.data["module_catalog"][0]["connected"])

    def test_profile_updates_are_persisted(self):
        user = self.auth()
        response = self.client.patch(
            "/api/v1/sync-ai/jarvis/profile/",
            {
                "assistant_name": "Atlas",
                "goals": ["EMAIL", "BUSINESS"],
                "onboarding_step": 3,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        settings = CustomerSettings.objects.get(user=user)
        self.assertEqual(
            settings.finance_profile["jarvis"]["assistant_name"],
            "Atlas",
        )

    def test_founder_test_account_receives_full_entitlements_without_public_admin_label(self):
        self.auth("jacoblord7@outlook.com")
        response = self.client.get("/api/v1/sync-ai/jarvis/profile/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["plan"], "EXECUTIVE")
        self.assertTrue(response.data["entitlements"]["property_management"])
        self.assertNotIn("god", str(response.data).lower())

    def test_check_in_and_check_out_are_available(self):
        self.auth()
        self.assertEqual(
            self.client.post(
                "/api/v1/sync-ai/jarvis/check-in/",
                {},
                format="json",
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/sync-ai/jarvis/check-out/",
                {"reason": "BEDTIME"},
                format="json",
            ).status_code,
            200,
        )

    def test_checkout_requires_a_paid_plan(self):
        self.auth()
        response = self.client.post(
            "/api/v1/sync-ai/jarvis/billing/checkout/",
            {"plan": "BASIC"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    @patch("sync_ai.jarvis_product_views.stripe.checkout.Session.create")
    @patch.dict(
        "os.environ",
        {
            "STRIPE_SECRET_KEY": "sk_test_example",
            "STRIPE_JARVIS_PERSONAL_PRICE_ID": "price_personal",
            "FRONTEND_URL": "https://syncworksapp.com",
        },
    )
    def test_checkout_returns_to_established_jarvis_setup_route(self, create_session):
        self.auth()
        create_session.return_value.url = "https://checkout.stripe.com/test"

        response = self.client.post(
            "/api/v1/sync-ai/jarvis/billing/checkout/",
            {"plan": "PERSONAL"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        kwargs = create_session.call_args.kwargs
        self.assertEqual(
            kwargs["success_url"],
            "https://syncworksapp.com/upgrade?product=jarvis&checkout=success",
        )
        self.assertEqual(
            kwargs["cancel_url"],
            "https://syncworksapp.com/upgrade?product=jarvis&checkout=cancelled",
        )

    @patch("sync_ai.jarvis_product_views.stripe.billing_portal.Session.create")
    @patch.dict(
        "os.environ",
        {
            "STRIPE_SECRET_KEY": "sk_test_example",
            "FRONTEND_URL": "https://syncworksapp.com",
        },
    )
    def test_portal_returns_to_established_jarvis_setup_route(self, create_portal):
        user = self.auth()
        UserBillingProfile.objects.create(
            user=user,
            stripe_customer_id="cus_example",
        )
        create_portal.return_value.url = "https://billing.stripe.com/test"

        response = self.client.post(
            "/api/v1/sync-ai/jarvis/billing/portal/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        kwargs = create_portal.call_args.kwargs
        self.assertEqual(
            kwargs["return_url"],
            "https://syncworksapp.com/upgrade?product=jarvis",
        )
