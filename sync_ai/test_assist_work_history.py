from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase
from user_accounts.models import AuditLog

BASE = "/api/v1/sync-ai/assist/pilot/workday/"
HISTORY = BASE + "history/"


@override_settings(REST_FRAMEWORK={
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
})
class WorkHistoryTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="history-founder", email="jacoblord7@outlook.com", password="test12345")
        self.other = User.objects.create_user(username="history-stranger", email="stranger@example.net", password="test12345")
        self.client.force_authenticate(self.owner)

    def test_owner_can_revisit_all_versions_and_receipts_without_mutation(self):
        created = self.client.post(BASE, {
            "goal": "Prepare a history-backed internal summary",
            "steps": [{"role": "RESEARCH_ANALYST", "task": "Check owner data"}],
        }, format="json")
        self.assertEqual(created.status_code, 201)
        goal_id = created.data["created_goal_id"]
        executed = self.client.post(BASE + goal_id + "/run/")
        self.assertEqual(executed.status_code, 200)
        self.assertEqual(executed.data["last_execution"]["status"], "BLOCKED")
        step = created.data["goals"][0]["steps"][0]
        reviewed = self.client.post(BASE + goal_id + "/steps/" + step["id"] + "/", {
            "status": "IN_PROGRESS", "evidence": "Reviewed missing source records.",
        }, format="json")
        self.assertEqual(reviewed.status_code, 200)
        before = AuditLog.objects.filter(actor=self.owner, action__startswith="sync_assist.workday.").count()
        history = self.client.get(HISTORY + "?goal_id=" + goal_id)
        self.assertEqual(history.status_code, 200)
        self.assertEqual([e["kind"] for e in history.data["events"]],
                         ["OWNER_PROGRESS", "WORKER_RECEIPT", "GOAL_CREATED"])
        self.assertEqual(history.data["events"][1]["status"], "BLOCKED")
        self.assertEqual(history.data["events"][1]["messages_sent"], 0)
        self.assertEqual(history.data["events"][0]["evidence"], "Reviewed missing source records.")
        self.assertEqual(history.data["events"][2]["goal"], "Prepare a history-backed internal summary")
        self.assertEqual(AuditLog.objects.filter(actor=self.owner, action__startswith="sync_assist.workday.").count(), before)

    def test_other_user_cannot_read_owner_history(self):
        created = self.client.post(BASE, {
            "goal": "Owner private work", "steps": [{"role": "RESEARCH_ANALYST", "task": "Internal"}],
        }, format="json")
        goal_id = created.data["created_goal_id"]
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(HISTORY).status_code, 403)
        self.assertEqual(self.client.get(HISTORY + "?goal_id=" + goal_id).status_code, 403)
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get(HISTORY).status_code, [401, 403])

    def test_invalid_identifier_is_rejected(self):
        self.assertEqual(self.client.get(HISTORY + "?goal_id=not-a-uuid").status_code, 400)
