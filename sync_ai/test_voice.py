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
class SyncVoiceTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="sync-voice-test",
            email="sync-voice-test@example.com",
            password="test-password-123",
        )
        token = Token.objects.create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_voice_status_does_not_expose_api_key(self):
        with patch.dict(
            "os.environ",
            {
                "ELEVENLABS_API_KEY": "secret-elevenlabs-key",
                "ELEVENLABS_SYNC_VOICE_ID": "kSiaSqSOAHNl8g8caZB5",
            },
        ):
            response = self.client.get("/api/v1/sync-ai/voice/status/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["configured"])
        self.assertEqual(
            response.data["voice_id"],
            "kSiaSqSOAHNl8g8caZB5",
        )
        self.assertNotIn("secret-elevenlabs-key", str(response.data))

    def test_voice_requires_text(self):
        response = self.client.post(
            "/api/v1/sync-ai/voice/synthesize/",
            {"text": ""},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    @patch("sync_ai.voice.requests.post")
    def test_voice_returns_audio(self, post):
        provider = Mock()
        provider.status_code = 200
        provider.content = b"fake-mp3-audio"
        provider.headers = {
            "content-type": "audio/mpeg",
            "request-id": "req_test",
            "character-cost": "42",
        }
        post.return_value = provider

        with patch.dict(
            "os.environ",
            {"ELEVENLABS_API_KEY": "secret-elevenlabs-key"},
        ):
            response = self.client.post(
                "/api/v1/sync-ai/voice/synthesize/",
                {"text": "What can I do for you today?"},
                format="json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "audio/mpeg")
        self.assertEqual(response.content, b"fake-mp3-audio")

    def test_voice_returns_browser_fallback_when_not_configured(self):
        with patch.dict("os.environ", {}, clear=True):
            response = self.client.post(
                "/api/v1/sync-ai/voice/synthesize/",
                {"text": "Read my summary."},
                format="json",
            )

        self.assertEqual(response.status_code, 503)
        self.assertTrue(response.data["browser_fallback"])
