from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient


class ForgeReflectionTests(TestCase):
    url = "/api/v1/sync-ai/forge/reflection/"

    def client_for(self, email):
        user = get_user_model().objects.create_user(
            username=email.split("@")[0], email=email, password="testpass123"
        )
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    @patch("sync_ai.forge_reflection_views.create_sync_response")
    def test_only_founder_can_access_reflection(self, provider):
        response = self.client_for("user@example.com").post(self.url, {
            "question": "What can I learn today?"
        }, format="json")
        self.assertEqual(response.status_code, 403)
        provider.assert_not_called()

    @patch("sync_ai.forge_reflection_views.ai_enabled", return_value=True)
    @patch("sync_ai.forge_reflection_views.create_sync_response")
    def test_owner_receives_grounded_answer(self, provider, _enabled):
        provider.return_value = Mock(text="Examine the assumption and practice one action.", model="test-model")
        response = self.client_for("jacoblord7@outlook.com").post(self.url, {
            "question": "How does this apply to my priorities?",
            "chapter_title": "Self command",
            "chapter_excerpt": "Consider the choices you can control.",
            "focus_areas": ["stoicism", "humility"],
            "approach": "reflective",
            "history": [{"role":"user", "text":"I struggle with distractions."}],
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Examine the assumption", response.data["answer"])
        _, kwargs = provider.call_args
        self.assertIn("I struggle with distractions", kwargs["message"])
        self.assertIn("NOT Sync Assist Chief of Staff", kwargs["instructions"])

    def test_oversized_history_rejected(self):
        response = self.client_for("jacoblord7@outlook.com").post(self.url, {
            "question": "Help me think.",
            "history": [{"role":"user", "text":"x"}] * 11,
        }, format="json")
        self.assertEqual(response.status_code, 400)
