from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from user_accounts.models import AuditLog


class GrowthCampaignAndOperationsTests(TestCase):
    def setUp(self):
        U = get_user_model()
        self.owner = U.objects.create_user(username="campaign-owner", email="jacoblord7@outlook.com", password="test123456")
        self.other = U.objects.create_user(username="campaign-other", email="someoneelse@example.net", password="test123456")
        self.client = APIClient()
        self.base = "/api/v1/sync-ai/assist/pilot/"

    def test_campaign_is_private_editable_and_never_activates_delivery(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(self.base + "growth/campaign/").status_code, 403)
        self.client.force_authenticate(self.owner)
        initial = self.client.get(self.base + "growth/campaign/")
        self.assertEqual(initial.status_code, 200)
        self.assertFalse(initial.data["sending_enabled"])
        payload = {"name": "Founding businesses", "offer": "A demo and current verified free trial", "call_to_action": "Interested?", "enabled": True}
        r = self.client.post(self.base + "growth/campaign/", payload, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["campaign"]["enabled"], False)
        self.assertFalse(r.data["offer_entitlements_changed"])
        updated = self.client.get(self.base + "growth/campaign/")
        self.assertEqual(updated.data["campaign"]["offer"], payload["offer"])

    def test_operations_are_pilot_only_and_never_claim_email_or_scheduler_connected(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(self.base + "operations/brief/").status_code, 403)
        self.client.force_authenticate(self.owner)
        r = self.client.get(self.base + "operations/brief/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["business_work"]["read_only"])
        self.assertFalse(r.data["email"]["connected"])
        self.assertFalse(r.data["email"]["send_enabled"])
        self.assertFalse(r.data["worker"]["verified"])
