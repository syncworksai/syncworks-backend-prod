from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from user_accounts.models import AuditLog

BASE = "/api/v1/sync-ai/assist/pilot/"


@override_settings(REST_FRAMEWORK={
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
})
class SyncAssistPilotTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="assist-pilot", email="jacoblord7@outlook.com", password="pass12345")
        self.other = User.objects.create_user(username="assist-outsider", email="elsewhere@example.com", password="pass12345")

    def test_only_authenticated_pilot_can_access(self):
        self.assertIn(self.client.get(BASE).status_code, [401, 403])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(BASE).status_code, 403)
        self.assertEqual(self.client.post(BASE, {"kind": "GENERAL", "title": "Forbidden"}).status_code, 403)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get(BASE).status_code, 200)

    def test_create_approve_and_no_execution(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(BASE, {"kind": "LEAD_FOLLOW_UP", "title": "Review lead", "description": "Draft a reply"}, format="json")
        self.assertEqual(response.status_code, 201)
        key = response.data["created_task_id"]
        decision_url = BASE + "tasks/" + key + "/decision/"
        response = self.client.post(decision_url, {"decision": "APPROVE"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["counts"]["approved"], 1)
        self.assertFalse(response.data["execution_enabled"])
        self.assertFalse(response.data["background_worker_enabled"])
        self.assertEqual(self.client.post(decision_url, {"decision": "REJECT"}).status_code, 409)
        self.assertEqual(AuditLog.objects.filter(actor=self.owner, action="sync_assist.pilot.task_approved").count(), 1)

    def test_cannot_access_other_account_task(self):
        self.client.force_authenticate(self.owner)
        created = self.client.post(BASE, {"title": "Private", "kind": "TICKET_REVIEW"}).data["created_task_id"]
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(BASE + "tasks/" + created + "/decision/", {"decision": "APPROVE"}).status_code, 403)

    def test_invalid_tasks_are_rejected(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(BASE, {"title": " ", "kind": "GENERAL"}).status_code, 400)
        self.assertEqual(self.client.post(BASE, {"title": "Valid", "kind": "PAYMENT"}).status_code, 400)

    def test_manual_scan_is_pilot_only_and_rate_limited(self):
        from user_accounts.models import Business, ServiceRequest
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(BASE + "scan/").status_code, 403)
        self.client.force_authenticate(self.owner)
        business = Business.objects.create(name="Pilot Scan", owner=self.owner)
        ServiceRequest.objects.create(customer=self.other, target_business=business, title="New job")
        result = self.client.post(BASE + "scan/")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["scan_result"]["created"], 1)
        self.assertEqual(result.data["counts"]["pending"], 1)
        self.assertEqual(self.client.post(BASE + "scan/").status_code, 429)
        self.assertFalse(result.data["background_worker_enabled"])
