from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient


class ForgeVoiceTests(TestCase):
    url = "/api/v1/customer-health/forge/voice/speak/"

    def _client(self, email):
        User = get_user_model()
        user = User.objects.create_user(
            username=email.split("@")[0], email=email, password="testpass123"
        )
        token = Token.objects.create(user=user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return client

    @override_settings(ELEVENLABS_API_KEY="test-key")
    @patch("customer_health.forge_voice_views.requests.post")
    def test_non_owner_cannot_generate_voice(self, post_mock):
        response = self._client("ordinary@example.com").post(
            self.url, {"text": "A sample lesson"}, format="json"
        )
        self.assertEqual(response.status_code, 403)
        post_mock.assert_not_called()

    @override_settings(ELEVENLABS_API_KEY="test-key")
    @patch("customer_health.forge_voice_views.requests.post")
    def test_owner_can_generate_narration(self, post_mock):
        upstream = Mock(ok=True, content=b"mp3-bytes")
        upstream.status_code = 200
        post_mock.return_value = upstream
        response = self._client("jacoblord7@outlook.com").post(
            self.url, {"text": "Make today count.", "energy": "calm"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"mp3-bytes")
        self.assertEqual(response["X-SyncWorks-Voice-Provider"], "elevenlabs")
        self.assertEqual(post_mock.call_args.kwargs["json"]["text"], "Make today count.")
        self.assertIn("EI3BL0ECeQayX8N4doHx", post_mock.call_args.args[0])
        self.assertEqual(response["X-SyncWorks-Forge-Voice"], "tucker")

    @override_settings(ELEVENLABS_API_KEY="test-key")
    def test_long_voice_request_rejected(self):
        response = self._client("jacoblord7@outlook.com").post(
            self.url, {"text": "a" * 901}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    @override_settings(ELEVENLABS_API_KEY="")
    def test_missing_key_reports_unavailable(self):
        response = self._client("jacoblord7@outlook.com").post(
            self.url, {"text": "A sample lesson."}, format="json"
        )
        self.assertEqual(response.status_code, 503)

    @override_settings(ELEVENLABS_API_KEY="test-key")
    @patch("customer_health.forge_voice_views.requests.post")
    def test_select_different_mature_narrator(self, post_mock):
        post_mock.return_value = Mock(ok=True, status_code=200, content=b"test-mp3")
        response = self._client("jacoblord7@outlook.com").post(
            self.url, {"text": "A deliberate breath.", "voice_key": "ambrose"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("gRPwZFYxBbXTrxXJzU6u", post_mock.call_args.args[0])

    @override_settings(ELEVENLABS_API_KEY="test-key")
    @patch("customer_health.forge_voice_views.requests.post")
    def test_rejects_arbitrary_voice_id(self, post_mock):
        response = self._client("jacoblord7@outlook.com").post(
            self.url, {"text": "A deliberate breath.", "voice_key": "my-secret-voice"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        post_mock.assert_not_called()
