from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from user_accounts.models import CustomerSettings


User = get_user_model()


class UserJarvisProductTests(APITestCase):
    def auth(self, email="assistant@example.com"):
        user = User.objects.create_user(username=email.split("@")[0], email=email, password="test-password-123")
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return user

    def test_profile_requires_authentication(self):
        response = self.client.get("/api/v1/sync-ai/assistant/profile/")
        self.assertEqual(response.status_code, 401)

    def test_basic_profile_has_marketplace_first_and_sync_assistant_name(self):
        self.auth()
        response = self.client.get("/api/v1/sync-ai/assistant/profile/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["product_name"], "SYNC Assistant")
        self.assertEqual(response.data["plan"], "BASIC")
        self.assertEqual(response.data["module_catalog"][0]["id"], "marketplace")
        self.assertTrue(response.data["module_catalog"][0]["connected"])
        self.assertEqual(response.data["live_addon"]["price"], 1.0)

    def test_legacy_jarvis_profile_route_still_works(self):
        self.auth()
        response = self.client.get("/api/v1/sync-ai/jarvis/profile/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["product_name"], "SYNC Assistant")

    def test_profile_updates_are_persisted_under_sync_assistant_key(self):
        user = self.auth()
        response = self.client.patch(
            "/api/v1/sync-ai/assistant/profile/",
            {
                "assistant_name": "SYNC",
                "goals": ["IMPORTANT_EMAIL", "BUSINESS"],
                "timezone": "America/Chicago",
                "live": {"news_topics": ["markets"], "sports": [{"league": "MLB", "team": "Atlanta Braves"}]},
                "onboarding_step": 3,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        settings = CustomerSettings.objects.get(user=user)
        stored = settings.finance_profile["sync_assistant"]
        self.assertEqual(stored["assistant_name"], "SYNC")
        self.assertEqual(stored["live"]["news_topics"], ["markets"])

    def test_founder_test_account_receives_full_and_live_entitlements(self):
        self.auth("jacoblord7@outlook.com")
        response = self.client.get("/api/v1/sync-ai/assistant/profile/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["plan"], "EXECUTIVE")
        self.assertTrue(response.data["entitlements"]["property_management"])
        self.assertTrue(response.data["entitlements"]["sync_assistant_live"])
        self.assertTrue(response.data["live"]["access"])
        self.assertNotIn("god", str(response.data).lower())

    def test_founder_live_checkout_never_requires_payment(self):
        self.auth("jacoblord7@outlook.com")
        response = self.client.post("/api/v1/sync-ai/assistant/billing/live/checkout/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["test_access"])
        self.assertTrue(response.data["activated"])

    def test_check_in_and_check_out_are_available(self):
        self.auth()
        self.assertEqual(self.client.post("/api/v1/sync-ai/assistant/check-in/", {}, format="json").status_code, 200)
        self.assertEqual(self.client.post("/api/v1/sync-ai/assistant/check-out/", {"reason": "BEDTIME"}, format="json").status_code, 200)

    def test_checkout_requires_a_paid_plan(self):
        self.auth()
        response = self.client.post("/api/v1/sync-ai/assistant/billing/checkout/", {"plan": "BASIC"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_daily_state_is_authenticated_and_does_not_invent_email_or_news(self):
        self.auth()
        response = self.client.get("/api/v1/sync-ai/assistant/daily-state/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["product_name"], "SYNC Assistant")
        self.assertFalse(response.data["email"]["available"])
        self.assertFalse(response.data["news"]["available"])
        self.assertIn("recommended_next", response.data)
