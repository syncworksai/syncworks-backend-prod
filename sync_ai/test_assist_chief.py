from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from unittest.mock import patch

BASE="/api/v1/sync-ai/assist/pilot/chief/"
class ChiefOfStaffTests(TestCase):
    def setUp(self):
        U=get_user_model()
        self.pilot=U.objects.create_user(username="chiefpilot",email="jacoblord7@outlook.com",password="testpassword")
        self.other=U.objects.create_user(username="chiefother",email="different@example.org",password="testpassword")
        self.client=APIClient()

    def test_private_pilot_only(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(BASE+"brief/").status_code,403)
        self.assertEqual(self.client.get(BASE+"cases/").status_code,403)
        self.assertEqual(self.client.post(BASE+"cases/",{},format="json").status_code,403)
        self.assertEqual(self.client.post(BASE+"cases/anything/decision/",{},format="json").status_code,403)

    def test_open_case_persists_and_requires_explicit_resolution(self):
        self.client.force_authenticate(self.pilot)
        created=self.client.post(BASE+"cases/",{
            "title":"MHA / Adair reconciliation",
            "details":"Owner-entered allegation pending verification.",
            "next_step":"Review the latest correspondence",
            "category":"PROPERTY","priority":"HIGH"
        },format="json")
        self.assertEqual(created.status_code,201)
        cid=created.data["case_id"]
        first=self.client.get(BASE+"cases/")
        self.assertEqual(first.data["cases"][0]["status"],"OPEN")
        self.assertEqual(first.data["cases"][0]["source"],"owner_entered")
        waiting=self.client.post(BASE+f"cases/{cid}/decision/",{"status":"WAITING"},format="json")
        self.assertEqual(waiting.status_code,200)
        self.assertEqual(waiting.data["cases"][0]["status"],"WAITING")
        bad=self.client.post(BASE+f"cases/{cid}/decision/",{"status":"RESOLVED","resolution_note":""},format="json")
        self.assertEqual(bad.status_code,400)
        self.assertEqual(self.client.get(BASE+"cases/").data["cases"][0]["status"],"WAITING")
        resolved=self.client.post(BASE+f"cases/{cid}/decision/",{"status":"RESOLVED","resolution_note":"Confirmed by owner following reconciliation."},format="json")
        self.assertEqual(resolved.status_code,200)
        self.assertEqual(resolved.data["cases"][0]["status"],"RESOLVED")

    def test_snapshot_is_on_demand_and_does_not_claim_external_coverage(self):
        self.client.force_authenticate(self.pilot)
        result=self.client.get(BASE+"brief/")
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.data["mode"],"on_demand")
        self.assertFalse(result.data["auto_send"])
        self.assertFalse(result.data["scheduled_delivery"])
        self.assertFalse(result.data["verified_health_monitoring"])
        self.assertEqual(len(result.data["sections"]),5)
        self.assertTrue(any(section["key"] == "delegation" for section in result.data["sections"]))

    def test_case_not_accessible_from_other_account(self):
        self.client.force_authenticate(self.pilot)
        r=self.client.post(BASE+"cases/",{
            "title":"Test","details":"","next_step":"","category":"BUSINESS","priority":"LOW"
        },format="json")
        cid=r.data["case_id"]
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(BASE+f"cases/{cid}/decision/",{"status":"WAITING"},format="json").status_code,403)
