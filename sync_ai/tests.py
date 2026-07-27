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
        "DEFAULT_THROTTLE_RATES": {"sync_ai": "100/min"},
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
