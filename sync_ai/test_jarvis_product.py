from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from user_accounts.models import CustomerSettings


User = get_user_model()


class UserJarvisProductTests(APITestCase):
    def auth(self, email="jarvis@example.com"):
        user = User.objects.create_user(username=email.split("@")[0], email=email, password="test-password-123")
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
            {"assistant_name": "Atlas", "goals": ["EMAIL", "BUSINESS"], "onboarding_step": 3},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        settings = CustomerSettings.objects.get(user=user)
        self.assertEqual(settings.finance_profile["jarvis"]["assistant_name"], "Atlas")

    def test_founder_test_account_receives_full_entitlements_without_public_admin_label(self):
        self.auth("jacoblord7@outlook.com")
        response = self.client.get("/api/v1/sync-ai/jarvis/profile/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["plan"], "EXECUTIVE")
        self.assertTrue(response.data["entitlements"]["property_management"])
        self.assertNotIn("god", str(response.data).lower())

    def test_check_in_and_check_out_are_available(self):
        self.auth()
        self.assertEqual(self.client.post("/api/v1/sync-ai/jarvis/check-in/", {}, format="json").status_code, 200)
        self.assertEqual(self.client.post("/api/v1/sync-ai/jarvis/check-out/", {"reason": "BEDTIME"}, format="json").status_code, 200)

    def test_checkout_requires_a_paid_plan(self):
        self.auth()
        response = self.client.post("/api/v1/sync-ai/jarvis/billing/checkout/", {"plan": "BASIC"}, format="json")
        self.assertEqual(response.status_code, 400)
