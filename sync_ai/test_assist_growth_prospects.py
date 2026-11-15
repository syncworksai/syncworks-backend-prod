from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from user_accounts.models import AuditLog

BASE = "/api/v1/sync-ai/assist/pilot/growth/prospects/"


class SyncAssistGrowthTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="growth-owner", email="jacoblord7@outlook.com", password="test123456")
        self.other = User.objects.create_user(username="growth-other", email="unrelated@example.net", password="test123456")
        self.client = APIClient()

    def test_private_no_send_prospect_draft_and_stage(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(BASE).status_code, 403)
        self.client.force_authenticate(self.owner)
        r = self.client.post(BASE, {
            "company": "Local Plumbing", "niche": "home_services",
            "website": "https://example.com", "channel": "MESSENGER",
            "observation": "your website lists plumbing and HVAC services",
        }, format="json")
        self.assertEqual(r.status_code, 201)
        pid = r.data["created_prospect_id"]
        self.assertFalse(r.data["outbound_automation_enabled"])
        self.assertEqual(r.data["prospects"][0]["stage"], "READY_FOR_REVIEW")
        self.assertIn("Local Plumbing", r.data["prospects"][0]["draft"])
        self.assertEqual(self.client.post(BASE, {"company": "local plumbing", "niche": "home_services"}, format="json").status_code, 409)
        s = self.client.post(BASE + pid + "/stage/", {"stage": "CONTACTED_MANUALLY"}, format="json")
        self.assertEqual(s.status_code, 200)
        self.assertEqual(s.data["prospects"][0]["stage"], "CONTACTED_MANUALLY")
        self.assertFalse(AuditLog.objects.filter(actor=self.owner, action__icontains="message_sent").exists())

    def test_bad_inputs_are_rejected(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(BASE, {"company": "Test", "niche": "home_services", "website": "javascript:alert(1)"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(BASE, {"company": "Test", "niche": "unknown"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(BASE + "not-a-uuid/stage/", {"stage": "CONTACTED_MANUALLY"}, format="json").status_code, 400)
