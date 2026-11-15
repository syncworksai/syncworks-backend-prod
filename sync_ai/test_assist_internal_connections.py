from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from user_accounts.models import Business, BusinessMember, PMProperty

URL = "/api/v1/sync-ai/assist/pilot/internal-connections/"


class InternalConnectionsTests(TestCase):
    def setUp(self):
        U = get_user_model()
        self.owner = U.objects.create_user(username="assist-owner-internal", email="jacoblord7@outlook.com", password="safe-test-123")
        self.other = U.objects.create_user(username="assist-outsider-internal", email="outside-connection@example.net", password="safe-test-123")
        self.client = APIClient()

    def test_pilot_sees_owned_but_not_unrelated_records(self):
        biz = Business.objects.create(owner=self.owner, name="SyncWorks Pilot", facebook_url="https://www.facebook.com/example")
        PMProperty.objects.create(business=biz, name="Test property")
        Business.objects.create(owner=self.other, name="Unrelated")
        self.client.force_authenticate(self.owner)
        result = self.client.get(URL)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["counts"]["visible"], 1)
        entry = result.data["internal_businesses"][0]
        self.assertEqual(entry["name"], "SyncWorks Pilot")
        self.assertEqual(entry["properties"], 1)
        self.assertEqual(entry["social"][0]["status"], "profile_saved")
        self.assertFalse(entry["social"][0]["api_connected"])
        self.assertFalse(result.data["external_social_automation_enabled"])

    def test_manager_visibility_does_not_grant_scanner_ownership(self):
        biz = Business.objects.create(owner=self.other, name="Managed PM")
        BusinessMember.objects.create(business=biz, user=self.owner, role="MANAGER", is_active=True)
        self.client.force_authenticate(self.owner)
        result = self.client.get(URL)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["internal_businesses"][0]["access"], "manager")
        self.assertFalse(result.data["internal_businesses"][0]["scan_eligible"])
        self.assertEqual(result.data["counts"]["scan_eligible"], 0)

    def test_nonpilot_cannot_read_connections(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(URL).status_code, 403)
