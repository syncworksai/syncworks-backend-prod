from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase


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
            username="sync-test-user",
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
        self.assertIn("property_management", response.data["workspaces"])
        self.assertNotIn("secret-test-key", str(response.data))

    @patch("sync_ai.service.requests.post")
    def test_personal_chat(self, post):
        provider = Mock()
        provider.status_code = 200
        provider.json.return_value = {
            "id": "resp_test",
            "model": "gpt-5-mini",
            "output_text": "Your next appointment is ready to review.",
            "usage": {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
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

    @patch("sync_ai.service.requests.post")
    def test_property_management_briefing_uses_sanitized_context(self, post):
        provider = Mock()
        provider.status_code = 200
        provider.json.return_value = {
            "id": "resp_pm_test",
            "model": "gpt-5-mini",
            "output_text": "One urgent work order needs attention.",
            "usage": {"input_tokens": 24, "output_tokens": 9, "total_tokens": 33},
        }
        post.return_value = provider

        with patch.dict("os.environ", {"OPENAI_API_KEY": "secret-test-key"}):
            response = self.client.post(
                "/api/v1/sync-ai/chat/",
                {
                    "workspace": "property_management",
                    "message": "Give me my PM briefing.",
                    "context": {
                        "property_count": 4,
                        "urgent_work_order_count": 1,
                        "api_key": "must-not-pass-through",
                        "priority_work_orders": [
                            {"title": "Water leak", "property": "North Building", "priority": "P1"}
                        ],
                    },
                },
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["workspace"], "property_management")
        request_body = post.call_args.kwargs["data"]
        self.assertNotIn("must-not-pass-through", request_body)
        self.assertIn("urgent_work_order_count", request_body)
