from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from user_accounts.models import AuditLog

BASE = "/api/v1/sync-ai/assist/pilot/workday/"

@override_settings(REST_FRAMEWORK={
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
})
class WorkdayPilotTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="workday-owner", email="jacoblord7@outlook.com", password="test12345")
        self.other = User.objects.create_user(username="workday-other", email="not-pilot@example.com", password="test12345")

    def _create(self):
        return self.client.post(BASE, {
            "goal": "Build a qualified prospect list",
            "steps": [
                {"role": "RESEARCH_ANALYST", "task": "Research business prospects"},
                {"role": "SALES_MANAGER", "task": "Prepare drafts for owner review"},
            ],
        }, format="json")

    def test_private_scope(self):
        self.assertIn(self.client.get(BASE).status_code, [401, 403])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(BASE).status_code, 403)
        self.assertEqual(self._create().status_code, 403)
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get(BASE).status_code, 200)

    def test_creates_assignments_but_does_not_claim_execution(self):
        self.client.force_authenticate(self.owner)
        response = self._create()
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["execution_enabled"])
        self.assertEqual(response.data["counts"]["planned"], 1)
        self.assertEqual(len(response.data["goals"][0]["steps"]), 2)
        self.assertEqual(
            AuditLog.objects.filter(actor=self.owner, action="sync_assist.workday.goal_created").count(), 1
        )

    def test_completion_requires_real_owner_attestation(self):
        self.client.force_authenticate(self.owner)
        created = self._create().data["goals"][0]
        step = created["steps"][0]
        url = BASE + created["id"] + "/steps/" + step["id"] + "/"
        self.assertEqual(self.client.post(url, {"status": "COMPLETED", "evidence": "fine"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"status": "COMPLETED", "owner_attested": True, "evidence": "fine"}, format="json").status_code, 400)
        completed = self.client.post(url, {"status": "COMPLETED", "owner_attested": True, "evidence": "I checked the generated source documents."}, format="json")
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.data["goals"][0]["steps"][0]["verified_by"], "owner")
        self.assertEqual(completed.data["goals"][0]["status"], "IN_PROGRESS")
        self.assertEqual(self.client.post(url, {"status": "PLANNED"}, format="json").status_code, 409)

    def test_rejects_bad_roles_and_cross_account_mutation(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.post(BASE, {"goal": "a", "steps": [{"role": "UNRESTRICTED", "task": "Anything"}]}, format="json").status_code, 400)
        created = self._create().data["goals"][0]
        step = created["steps"][0]
        self.client.force_authenticate(self.other)
        url = BASE + created["id"] + "/steps/" + step["id"] + "/"
        self.assertEqual(self.client.post(url, {"status": "IN_PROGRESS"}, format="json").status_code, 403)

    def test_all_assignments_must_be_attested_for_goal_completion(self):
        self.client.force_authenticate(self.owner)
        goal = self._create().data["goals"][0]
        for step in goal["steps"]:
            response = self.client.post(BASE + goal["id"] + "/steps/" + step["id"] + "/", {
                "status": "COMPLETED", "owner_attested": True,
                "evidence": "I verified the completed output and supporting record.",
            }, format="json")
            self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["goals"][0]["status"], "COMPLETED")
        self.assertEqual(response.data["counts"]["completed"], 1)
