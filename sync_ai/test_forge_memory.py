from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from customer_health.models import ForgePersonalProfile, ForgeConversationEntry


class ForgeProfileAndMemoryTests(TestCase):
    profile_url = "/api/v1/sync-ai/forge/profile/"
    history_url = "/api/v1/sync-ai/forge/history/?chapter=self-command"
    reflection_url = "/api/v1/sync-ai/forge/reflection/"

    def client_for(self, email):
        user = get_user_model().objects.create_user(
            username=email.split("@")[0], email=email, password="testpass123"
        )
        client = APIClient()
        client.force_authenticate(user=user)
        return user, client

    def test_profile_owner_only_and_validation(self):
        other, client = self.client_for("other@example.com")
        self.assertEqual(client.get(self.profile_url).status_code, 403)
        self.assertEqual(client.patch(self.profile_url, {"memory_enabled": True}, format="json").status_code, 403)
        owner, client = self.client_for("jacoblord7@outlook.com")
        self.assertFalse(client.get(self.profile_url).data["memory_enabled"])
        self.assertEqual(client.patch(self.profile_url, {"focus_areas": ["invalid"]}, format="json").status_code, 400)
        self.assertEqual(client.patch(self.profile_url, {"memory_enabled": "yes"}, format="json").status_code, 400)
        response = client.patch(self.profile_url, {
            "focus_areas": ["stoicism", "humility"],
            "approach": "challenging",
            "personal_vision": "Act with calm courage and be present with my family.",
            "current_challenge": "I try to do everything.",
            "daily_practice": "Meditate ten minutes.",
            "assessment_completed": True,
            "memory_enabled": True,
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["coaching_style"] if "coaching_style" in response.data else response.data["approach"], "challenging")
        self.assertEqual(client.get(self.profile_url).data["personal_vision"], "Act with calm courage and be present with my family.")

    @patch("sync_ai.forge_reflection_views.ai_enabled", return_value=True)
    @patch("sync_ai.forge_reflection_views.create_sync_response")
    def test_opt_in_persists_profile_context_and_history(self, provider, _enabled):
        owner, client = self.client_for("jacoblord7@outlook.com")
        client.patch(self.profile_url, {
            "focus_areas": ["stoicism"], "personal_vision": "Be a patient father.",
            "assessment_completed": True, "memory_enabled": True,
        }, format="json")
        provider.return_value = Mock(text="Your practice is to pause before reacting.", model="test")
        response = client.post(self.reflection_url, {
            "question": "How do I respond more patiently?",
            "chapter_key": "self-command",
            "chapter_title": "Self-command",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["saved"])
        self.assertIn("Be a patient father.", provider.call_args.kwargs["message"])
        messages = client.get(self.history_url).data["messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[1]["role"], "coach")
        provider.return_value = Mock(text="The next step is a short reflection.", model="test")
        client.post(self.reflection_url, {
            "question": "What is my next step?", "chapter_key": "self-command"
        }, format="json")
        self.assertIn("pause before reacting", provider.call_args.kwargs["message"])

    @patch("sync_ai.forge_reflection_views.ai_enabled", return_value=True)
    @patch("sync_ai.forge_reflection_views.create_sync_response")
    def test_without_consent_no_history_is_stored(self, provider, _enabled):
        _, client = self.client_for("jacoblord7@outlook.com")
        provider.return_value = Mock(text="Reflection", model="test")
        response = client.post(self.reflection_url, {
            "question": "What do I control?", "chapter_key": "self-command"
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["saved"])
        self.assertEqual(client.get(self.history_url).data["messages"], [])

    def test_revoking_memory_deletes_history_and_full_reset(self):
        owner, client = self.client_for("jacoblord7@outlook.com")
        client.patch(self.profile_url, {"memory_enabled": True}, format="json")
        ForgeConversationEntry.objects.create(user=owner, chapter_key="self-command", role="user", text="A private thought")
        self.assertEqual(client.get(self.history_url).data["messages"][0]["text"], "A private thought")
        client.patch(self.profile_url, {"memory_enabled": False}, format="json")
        self.assertFalse(ForgeConversationEntry.objects.filter(user=owner).exists())
        self.assertEqual(client.delete(self.profile_url).status_code, 204)
        self.assertFalse(ForgePersonalProfile.objects.filter(user=owner).exists())
