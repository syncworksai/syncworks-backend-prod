from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from user_accounts.models.audit import AuditLog


class SyncUsageApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="sync-usage",
            email="sync-usage@example.com",
            password="test-password-123",
        )
        token, _ = Token.objects.get_or_create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def authenticate(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_tracks_only_allowlisted_usage_metadata(self):
        response = self.client.post(
            "/api/v1/sync-ai/usage/track/",
            {
                "area": "calendar",
                "action": "quick_add",
                "metadata": {
                    "category": "appointment",
                    "scheduling_mode": "fixed",
                    "batch": True,
                    "raw_text": "Private appointment contents",
                    "balance": "9999.99",
                    "address": "123 Private Street",
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        row = AuditLog.objects.get(actor=self.user)
        self.assertEqual(row.action, "SYNC_USAGE:CALENDAR:QUICK_ADD")
        self.assertEqual(row.metadata["category"], "appointment")
        self.assertEqual(row.metadata["scheduling_mode"], "fixed")
        self.assertTrue(row.metadata["batch"])
        self.assertNotIn("raw_text", row.metadata)
        self.assertNotIn("balance", row.metadata)
        self.assertNotIn("address", row.metadata)

    def test_summary_is_user_scoped(self):
        other = get_user_model().objects.create_user(
            username="other-usage",
            email="other-usage@example.com",
            password="test-password-123",
        )
        AuditLog.objects.create(actor=other, action="SYNC_USAGE:FINANCE:ADD_DEBT", metadata={})
        AuditLog.objects.create(actor=self.user, action="SYNC_USAGE:CALENDAR:QUICK_ADD", metadata={"completed": True})
        AuditLog.objects.create(actor=self.user, action="SYNC_USAGE:HEALTH:WEIGH_IN", metadata={"completed": True})

        response = self.client.get("/api/v1/sync-ai/usage/summary/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["action_count"], 2)
        self.assertEqual(response.data["module_count"], 2)
        self.assertEqual(response.data["completed_actions"], 2)
        self.assertGreater(response.data["score"], 0)
        self.assertNotIn("FINANCE", [item["area"] for item in response.data["top_areas"]])

    def test_god_mode_summary_is_aggregate_and_admin_only(self):
        AuditLog.objects.create(actor=self.user, action="SYNC_USAGE:CALENDAR:QUICK_ADD_SAVED", metadata={"category": "APPOINTMENT", "completed": True})
        denied = self.client.get("/api/v1/sync-ai/usage/god-mode/summary/")
        self.assertEqual(denied.status_code, 403)

        admin = get_user_model().objects.create_superuser(
            username="usage-admin",
            email="usage-admin@example.com",
            password="test-password-123",
        )
        self.authenticate(admin)
        response = self.client.get("/api/v1/sync-ai/usage/god-mode/summary/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["tracked_users"], 1)
        self.assertEqual(response.data["action_count"], 1)
        self.assertEqual(response.data["top_areas"][0]["area"], "CALENDAR")
        self.assertEqual(response.data["top_categories"][0]["category"], "APPOINTMENT")

    def test_rejects_unknown_area(self):
        response = self.client.post(
            "/api/v1/sync-ai/usage/track/",
            {"area": "unknown", "action": "click"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
