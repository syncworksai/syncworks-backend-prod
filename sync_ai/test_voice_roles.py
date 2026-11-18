"""Role voice routing tests; no network requests or paid synthesis."""
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from .voice import configured_voice_id, SyncVoiceConfigurationError, synthesize_sync_voice

BASE = "/api/v1/sync-ai/voice/"

class VoiceRoleTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="voice-role-test", email="voicerole@example.com", password="pass12345")
        self.client.force_authenticate(self.user)

    def test_role_config_reads_from_environment(self):
        with patch.dict("os.environ", {
            "ELEVENLABS_SYNC_VOICE_ID": "sync-test-id",
            "ELEVENLABS_FORGE_VOICE_ID": "forge-test-id",
            "ELEVENLABS_GEMMA_VOICE_ID": "gemma-test-id",
            "ELEVENLABS_HEALTH_VOICE_ID": "health-test-id",
        }):
            self.assertEqual(configured_voice_id("forge"), "forge-test-id")
            self.assertEqual(configured_voice_id("female_assistant"), "gemma-test-id")
            self.assertEqual(configured_voice_id("health"), "health-test-id")

    def test_missing_specialist_voice_does_not_use_wrong_voice(self):
        with patch.dict("os.environ", {"ELEVENLABS_GEMMA_VOICE_ID": "", "ELEVENLABS_API_KEY": "dummy"}):
            self.assertEqual(configured_voice_id("female_assistant"), "")
            with self.assertRaises(SyncVoiceConfigurationError):
                synthesize_sync_voice("Hello", role="female_assistant")

    def test_invalid_role_rejected_without_provider_call(self):
        result = self.client.post(BASE + "synthesize/", {"text": "Hello", "role": "unknown"}, format="json")
        self.assertEqual(result.status_code, 400)

    def test_status_reports_profiles_without_secret_key(self):
        result = self.client.get(BASE + "status/")
        self.assertEqual(result.status_code, 200)
        self.assertIn("forge", result.data["roles"])
        self.assertIn("female_assistant", result.data["roles"])
        self.assertIn("health", result.data["roles"])
        self.assertNotIn("api_key", result.data)
