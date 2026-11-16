from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from user_accounts.models import AuditLog
from .employee_catalog import CATALOG

BASE = "/api/v1/sync-ai/assist/employees/"
ASSIGNMENTS = BASE + "assignments/"


@override_settings(REST_FRAMEWORK={
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
})
class AIEmployeeBetaTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="roster_owner", email="roster@example.com", password="pass12345")
        self.other = User.objects.create_user(username="roster_other", email="other@example.com", password="pass12345")

    def test_auth_and_catalog_and_no_charges(self):
        self.assertIn(self.client.get(BASE).status_code, [401, 403])
        self.client.force_authenticate(self.user)
        response = self.client.get(BASE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["employees"]), 12)
        self.assertFalse(response.data["billing_enabled"])
        self.assertFalse(response.data["execution_enabled"])
        self.assertTrue(next(e for e in response.data["employees"] if e["id"] == "chief_of_staff")["active"])
        self.assertEqual(set(CATALOG), {e["id"] for e in response.data["employees"]})

    def test_activation_persists_and_is_isolated(self):
        self.client.force_authenticate(self.user)
        url = BASE + "lead_scout/activation/"
        self.assertEqual(self.client.post(url, {"action": "ACTIVATE"}).status_code, 200)
        self.assertEqual(self.client.post(url, {"action": "ACTIVATE"}).status_code, 200)
        self.assertEqual(AuditLog.objects.filter(actor=self.user, action="sync_assist.employee.activate").count(), 1)
        self.client.force_authenticate(self.other)
        self.assertFalse(next(e for e in self.client.get(BASE).data["employees"] if e["id"] == "lead_scout")["active"])
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(url, {"action": "DEACTIVATE"}).status_code, 200)
        self.assertFalse(next(e for e in self.client.get(BASE).data["employees"] if e["id"] == "lead_scout")["active"])

    def test_assignment_is_saved_but_never_executed(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(ASSIGNMENTS, {
            "employee_id": "lead_scout", "title": "Find leads", "instructions": "Find landscaping businesses"
        }).status_code, 403)
        self.client.post(BASE + "lead_scout/activation/", {"action": "ACTIVATE"})
        result = self.client.post(ASSIGNMENTS, {
            "employee_id": "lead_scout", "title": "Find leads", "instructions": "Find landscaping businesses"
        })
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.data["status"], "QUEUED_FOR_REVIEW")
        self.assertFalse(result.data["execution_enabled"])
        self.assertEqual(len(self.client.get(ASSIGNMENTS).data["assignments"]), 1)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(ASSIGNMENTS).data["assignments"], [])

    def test_rejects_bad_inputs(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(BASE + "chief_of_staff/activation/", {"action": "DEACTIVATE"}).status_code, 400)
        self.assertEqual(self.client.post(BASE + "nonexistent/activation/", {"action": "ACTIVATE"}).status_code, 404)
        self.assertEqual(self.client.post(ASSIGNMENTS, {
            "employee_id": "chief_of_staff", "title": " ", "instructions": "Work"
        }).status_code, 400)
        self.assertEqual(self.client.post(ASSIGNMENTS, {
            "employee_id": "chief_of_staff", "title": "Work", "instructions": "x" * 2501
        }).status_code, 400)
