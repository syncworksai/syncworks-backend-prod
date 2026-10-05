from __future__ import annotations

from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .voice_views import DEFAULT_HEALTH_VOICE_ID, DEFAULT_HEALTH_VOICE_NAME


class HealthVoiceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="health-voice-user",
            email="health-voice@example.com",
            password="testpass123",
        )
        token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    @override_settings(
        ELEVENLABS_API_KEY="test-elevenlabs-key",
        ELEVENLABS_HEALTH_VOICE_ID=DEFAULT_HEALTH_VOICE_ID,
        ELEVENLABS_HEALTH_VOICE_NAME=DEFAULT_HEALTH_VOICE_NAME,
        ELEVENLABS_MODEL_ID="eleven_multilingual_v2",
    )
    def test_voice_options_reports_gemma_and_provider_ready(self):
        response = self.client.get("/api/v1/customer-health/voice/options/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["provider"], "elevenlabs")
        self.assertTrue(response.data["provider_ready"])
        self.assertTrue(response.data["browser_fallback"])
        self.assertEqual(
            response.data["default_voice_name"],
            "Gemma - SYNC Fitness Coach",
        )
        self.assertEqual(
            response.data["voices"][0]["name"],
            "Gemma - SYNC Fitness Coach",
        )

    @override_settings(
        ELEVENLABS_API_KEY="test-elevenlabs-key",
        ELEVENLABS_HEALTH_VOICE_ID=DEFAULT_HEALTH_VOICE_ID,
        ELEVENLABS_HEALTH_VOICE_NAME=DEFAULT_HEALTH_VOICE_NAME,
        ELEVENLABS_MODEL_ID="eleven_multilingual_v2",
    )
    @patch("customer_health.voice_views.requests.post")
    def test_speak_proxies_to_selected_elevenlabs_voice(self, post_mock):
        upstream = Mock()
        upstream.ok = True
        upstream.content = b"fake-mp3"
        upstream.headers = {
            "Content-Type": "audio/mpeg",
            "request-id": "req-123",
        }
        post_mock.return_value = upstream

        response = self.client.post(
            "/api/v1/customer-health/voice/speak/",
            {
                "text": "Strong setup. Control the rep and finish with confidence.",
                "event_type": "exercise_intro",
                "energy": "high_energy",
                "voice_key": "sync_fitness_coach",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"fake-mp3")
        self.assertEqual(
            response["X-SyncWorks-Voice-Name"],
            "Gemma - SYNC Fitness Coach",
        )
        self.assertEqual(response["X-SyncWorks-Voice-Provider"], "elevenlabs")

        args, kwargs = post_mock.call_args
        self.assertIn(DEFAULT_HEALTH_VOICE_ID, args[0])
        self.assertEqual(kwargs["json"]["model_id"], "eleven_multilingual_v2")
        self.assertEqual(kwargs["json"]["text"], "Strong setup. Control the rep and finish with confidence.")

    @override_settings(ELEVENLABS_API_KEY="")
    def test_speak_reports_not_configured_without_backend_key(self):
        response = self.client.post(
            "/api/v1/customer-health/voice/speak/",
            {
                "text": "Test coach cue",
                "event_type": "voice_preview",
                "energy": "balanced",
                "voice_key": "sync_fitness_coach",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "elevenlabs_not_configured")
