from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from platform_growth.models import PlatformActivationEvent, PlatformCampaign, PlatformConversation, PlatformLead, PlatformMessage


User = get_user_model()


@override_settings(GOD_MODE_EMAIL_ALLOWLIST=["god@example.com"], META_WEBHOOK_VERIFY_TOKEN="verify-123")
class TestPlatformGrowthPhase1(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.god = User.objects.create_user(username="god@example.com", email="god@example.com", password="Password123!")
        self.normal = User.objects.create_user(
            username="normal@example.com",
            email="normal@example.com",
            password="Password123!",
        )

    def test_dashboard_requires_god_mode(self):
        self.client.force_authenticate(user=self.normal)
        res = self.client.get("/api/v1/platform-growth/dashboard/")
        self.assertEqual(res.status_code, 403)

        self.client.force_authenticate(user=self.god)
        res = self.client.get("/api/v1/platform-growth/dashboard/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("campaigns", res.data)

    def test_campaign_crud_lite(self):
        self.client.force_authenticate(user=self.god)
        create = self.client.post("/api/v1/platform-growth/campaigns/", {"name": "Spring Push", "objective": "Leads"}, format="json")
        self.assertEqual(create.status_code, 201)
        campaign_id = create.data["id"]

        listing = self.client.get("/api/v1/platform-growth/campaigns/")
        self.assertEqual(listing.status_code, 200)
        self.assertGreaterEqual(len(listing.data), 1)

        patch = self.client.patch(
            f"/api/v1/platform-growth/campaigns/{campaign_id}/",
            {"status": "ACTIVE", "budget_cents": 12000},
            format="json",
        )
        self.assertEqual(patch.status_code, 200)

    def test_leads_conversation_messages_reply(self):
        self.client.force_authenticate(user=self.god)
        lead = PlatformLead.objects.create(full_name="Jane Lead", email="jane@example.com")
        convo = PlatformConversation.objects.create(lead=lead, external_thread_id="thread_1")
        PlatformMessage.objects.create(conversation=convo, direction=PlatformMessage.Direction.INBOUND, text="Hi")

        leads = self.client.get("/api/v1/platform-growth/leads/")
        self.assertEqual(leads.status_code, 200)
        detail = self.client.get(f"/api/v1/platform-growth/leads/{lead.id}/")
        self.assertEqual(detail.status_code, 200)

        update = self.client.patch(f"/api/v1/platform-growth/leads/{lead.id}/", {"status": "QUALIFIED"}, format="json")
        self.assertEqual(update.status_code, 200)

        msgs = self.client.get(f"/api/v1/platform-growth/conversations/{convo.id}/messages/")
        self.assertEqual(msgs.status_code, 200)
        self.assertEqual(len(msgs.data), 1)

        reply = self.client.post(f"/api/v1/platform-growth/conversations/{convo.id}/reply/", {"text": "Thanks"}, format="json")
        self.assertEqual(reply.status_code, 201)
        self.assertEqual(reply.data["direction"], PlatformMessage.Direction.OUTBOUND)

    def test_meta_webhook_verify_and_event_recording(self):
        verify = self.client.get(
            "/api/v1/platform-growth/meta/webhook/verify/?hub.mode=subscribe&hub.verify_token=verify-123&hub.challenge=abc123"
        )
        self.assertEqual(verify.status_code, 200)

        bad_verify = self.client.get(
            "/api/v1/platform-growth/meta/webhook/verify/?hub.mode=subscribe&hub.verify_token=nope&hub.challenge=abc123"
        )
        self.assertEqual(bad_verify.status_code, 403)

        payload = {
            "object": "page",
            "entry": [
                {"id": "entry_1", "changes": [{"field": "messages", "value": {"mid": "m_1", "text": "hello"}}]}
            ],
        }
        post = self.client.post("/api/v1/platform-growth/meta/webhook/", payload, format="json")
        self.assertEqual(post.status_code, 202)
        self.assertTrue(PlatformActivationEvent.objects.exists())
