from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from user_accounts.models import SyncAssistJob

BASE = "/api/v1/sync-ai/assist/pilot/workday/"


@override_settings(REST_FRAMEWORK={
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
})
class DurableWorkdayTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="queue-pilot", email="jacoblord7@outlook.com", password="test12345")
        self.other = User.objects.create_user(username="queue-outside", email="outside@example.com", password="test12345")
        self.client.force_authenticate(self.owner)

    def make_goal(self, mode="INTERNAL_ONLY"):
        payload = {
            "goal": "Prepare a documented prospect briefing",
            "steps": [{"role": "RESEARCH_ANALYST", "task": "Compile owner-entered business records"}],
            "source_mode": mode,
        }
        if mode == "PUBLIC_SEARCH":
            payload.update(public_search_query="plumbers Birmingham Alabama", allow_external_search=True)
        response = self.client.post(BASE, payload, format="json")
        self.assertEqual(response.status_code, 201)
        return response.data["created_goal_id"]

    def enroll(self, goal_id):
        return self.client.post(BASE + "jobs/", {
            "goal_id": goal_id, "allow_background_internal": True,
        }, format="json")

    def test_requires_explicit_consent_and_internal_sources(self):
        goal_id = self.make_goal()
        no_consent = self.client.post(BASE + "jobs/", {"goal_id": goal_id}, format="json")
        self.assertEqual(no_consent.status_code, 400)
        enrolled = self.enroll(goal_id)
        self.assertEqual(enrolled.status_code, 201)
        self.assertEqual(enrolled.data["job"]["state"], "QUEUED")
        self.assertEqual(self.enroll(goal_id).status_code, 200)
        self.assertEqual(SyncAssistJob.objects.filter(owner=self.owner).count(), 1)
        external = self.make_goal("PUBLIC_SEARCH")
        self.assertEqual(self.enroll(external).status_code, 400)

    def test_worker_runs_unattended_internal_step_with_receipt(self):
        from sync_ai.assist_job_queue import run_batch
        from user_accounts.models import AuditLog
        goal_id = self.make_goal()
        self.enroll(goal_id)
        results = run_batch(limit=1)
        self.assertEqual(results, ["WAITING"])
        job = SyncAssistJob.objects.get(owner=self.owner, goal_id=goal_id)
        self.assertEqual(job.state, SyncAssistJob.State.WAITING)
        self.assertIsNotNone(job.last_receipt_id)
        self.assertEqual(AuditLog.objects.filter(actor=self.owner, action="sync_assist.workday.worker_receipt").count(), 1)
        self.assertEqual(run_batch(limit=1), [])

    def test_cancel_and_cross_account_isolation(self):
        goal_id = self.make_goal()
        self.enroll(goal_id)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(BASE + "jobs/").status_code, 403)
        self.assertEqual(self.client.post(BASE + "jobs/" + goal_id + "/cancel/").status_code, 403)
        self.client.force_authenticate(self.owner)
        response = self.client.post(BASE + "jobs/" + goal_id + "/cancel/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["job"]["state"], "CANCELLED")
        from sync_ai.assist_job_queue import run_batch
        self.assertEqual(run_batch(limit=1), [])
        self.assertEqual(self.enroll(goal_id).status_code, 409)

    def test_worker_command_requires_explicit_enablement(self):
        from io import StringIO
        from unittest.mock import patch
        from django.core.management import call_command, CommandError
        self.enroll(self.make_goal())
        out = StringIO()
        call_command("sync_assist_queue_worker", "--dry-run", stdout=out)
        self.assertIn("Eligible persisted jobs: 1", out.getvalue())
        with patch.dict("os.environ", {"SYNC_ASSIST_DURABLE_WORKER_ENABLED": "false"}):
            with self.assertRaises(CommandError):
                call_command("sync_assist_queue_worker", "--once", stdout=StringIO())
