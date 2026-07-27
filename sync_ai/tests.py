from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from sync_ai.context import resolve_workspace
from user_accounts.models import Business, ServiceRequest, Ticket


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": [
            "rest_framework.authentication.TokenAuthentication",
        ],
        "DEFAULT_PERMISSION_CLASSES": [
            "rest_framework.permissions.IsAuthenticated",
        ],
    }
)
class SyncAITests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="sync-test",
            email="sync-test@example.com",
            password="test-password-123",
        )
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_status_does_not_expose_key(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "secret-test-key"}):
            response = self.client.get("/api/v1/sync-ai/status/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["configured"])
        self.assertNotIn("secret-test-key", str(response.data))

    @patch("sync_ai.service.requests.post")
    def test_personal_chat(self, post):
        provider = Mock()
        provider.status_code = 200
        provider.json.return_value = {
            "id": "resp_test",
            "model": "gpt-5-mini",
            "output_text": "Your next appointment is ready to review.",
            "usage": {
                "input_tokens": 12,
                "output_tokens": 8,
                "total_tokens": 20,
            },
        }
        post.return_value = provider

        with patch.dict("os.environ", {"OPENAI_API_KEY": "secret-test-key"}):
            response = self.client.post(
                "/api/v1/sync-ai/chat/",
                {"workspace": "personal", "message": "What is next?"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["workspace"], "personal")
        self.assertEqual(response.data["usage"]["total_tokens"], 20)

    def test_personal_snapshot_uses_existing_requests_and_tickets(self):
        request = ServiceRequest.objects.create(
            customer=self.user,
            title="Repair kitchen sink",
            status="NEW",
        )
        Ticket.objects.create(
            customer=self.user,
            service_request=request,
            work_title="Kitchen sink repair",
            status="SCHEDULED",
        )

        context = resolve_workspace(
            user=self.user,
            workspace="personal",
            business_id=None,
        )

        self.assertEqual(context.data["service_requests"]["active"], 1)
        self.assertEqual(context.data["tickets"]["active"], 1)
        self.assertEqual(context.data["tickets"]["scheduled"], 1)

    def test_business_snapshot_is_scoped_to_active_business(self):
        business = Business.objects.create(
            owner=self.user,
            name="SYNC Test Services",
        )
        Ticket.objects.create(
            customer=self.user,
            assigned_business=business,
            work_title="Blocked test job",
            status="IN_PROGRESS",
            total_amount_cents=12500,
        )

        context = resolve_workspace(
            user=self.user,
            workspace="business",
            business_id=str(business.id),
        )

        self.assertEqual(context.role, "OWNER")
        self.assertEqual(context.data["operations"]["active_jobs"], 1)
        self.assertEqual(
            context.data["operations"]["open_job_value_cents"],
            12500,
        )
