from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from user_accounts.models import AuditLog

URL = "/api/v1/sync-ai/assist/pilot/team/"


@override_settings(REST_FRAMEWORK={
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
})
class TeamConfigurationTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="team-owner", email="jacoblord7@outlook.com", password="test12345")
        self.other = User.objects.create_user(username="team-other", email="outside-team@example.org", password="test12345")
        self.client.force_authenticate(self.owner)

    def test_defaults_and_persistence(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["employees"]), 4)
        self.assertEqual(response.data["employees"][0]["name"], "Victoria")
        employees = [
            {"id": e["id"], "name": "Alex" if e["id"] == "executive-female" else e["name"], "role": e["role"]}
            for e in response.data["employees"]
        ]
        employees[0]["role"] = "EXECUTIVE_ASSISTANT"
        self.assertEqual(self.client.put(URL, {"employees": employees}, format="json").status_code, 200)
        saved = self.client.get(URL).data["employees"]
        self.assertEqual(saved[0]["name"], "Alex")
        self.assertEqual(saved[0]["role"], "EXECUTIVE_ASSISTANT")
        self.assertEqual(saved[0]["execution_status"], "internal_pilot")
        self.assertEqual(AuditLog.objects.filter(actor=self.owner, action="sync_assist.team.config_updated").count(), 1)

    def test_reject_invalid_role_duplicate_and_unknown_fields_without_write(self):
        default = self.client.get(URL).data["employees"]
        payload = [{"id": e["id"], "name": e["name"], "role": e["role"]} for e in default]
        payload[1]["role"] = payload[0]["role"]
        self.assertEqual(self.client.put(URL, {"employees": payload}, format="json").status_code, 400)
        payload[1]["role"] = "ROOT_ADMIN"
        self.assertEqual(self.client.put(URL, {"employees": payload}, format="json").status_code, 400)
        payload[1]["role"] = "SALES_MANAGER"
        payload[1]["privileges"] = ["god_mode"]
        self.assertEqual(self.client.put(URL, {"employees": payload}, format="json").status_code, 400)
        self.assertFalse(AuditLog.objects.filter(actor=self.owner, action="sync_assist.team.config_updated").exists())

    def test_nonpilot_denied_and_does_not_leak_owner_config(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(self.client.put(URL, {"employees": []}, format="json").status_code, 403)
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get(URL).status_code, [401, 403])
