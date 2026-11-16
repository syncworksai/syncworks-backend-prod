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

    def test_owner_attestation_finishes_persisted_job(self):
        from sync_ai.assist_job_queue import run_batch
        prospect = self.client.post("/api/v1/sync-ai/assist/pilot/growth/prospects/", {
            "company": "Sample Mechanical", "niche": "home_services",
            "website": "https://example.org", "channel": "EMAIL",
        }, format="json")
        self.assertEqual(prospect.status_code, 201)
        goal_id = self.make_goal()
        self.enroll(goal_id)
        self.assertEqual(run_batch(limit=1), ["WAITING"])
        goal = next(g for g in self.client.get(BASE).data["goals"] if g["id"] == goal_id)
        step = goal["steps"][0]
        self.assertEqual(step["worker_receipt"]["status"], "AWAITING_APPROVAL")
        confirmed = self.client.post(BASE + goal_id + "/steps/" + step["id"] + "/", {
            "status": "COMPLETED",
            "owner_attested": True,
            "evidence": "I reviewed the prospect source and the report output.",
        }, format="json")
        self.assertEqual(confirmed.status_code, 200)
        job = SyncAssistJob.objects.get(owner=self.owner, goal_id=goal_id)
        self.assertEqual(job.state, SyncAssistJob.State.SUCCEEDED)
        self.assertEqual(run_batch(limit=1), [])

    def test_exclusive_claim_and_retry_state(self):
        from sync_ai.assist_job_queue import claim_one, run_claimed
        goal_id = self.make_goal()
        self.enroll(goal_id)
        claimed = claim_one()
        self.assertIsNotNone(claimed)
        self.assertIsNone(claim_one())
        self.assertEqual(run_claimed(*claimed), "WAITING")
        self.assertEqual(SyncAssistJob.objects.get(goal_id=goal_id).state, "WAITING")

    def test_worker_health_requires_recorded_runs(self):
        from io import StringIO
        from unittest.mock import patch
        from django.core.management import call_command
        self.assertEqual(self.client.get(BASE + "jobs/").data["worker_status"], "not_verified")
        with patch.dict("os.environ", {"SYNC_ASSIST_DURABLE_WORKER_ENABLED": "true",
                         "SYNC_ASSIST_DURABLE_SCHEDULED_ENABLED": "true"}):
            call_command("sync_assist_queue_worker", "--once", stdout=StringIO())
            self.assertEqual(self.client.get(BASE + "jobs/").data["worker_status"], "not_verified")
            call_command("sync_assist_queue_worker", "--once", "--scheduled", stdout=StringIO())
            call_command("sync_assist_queue_worker", "--once", "--scheduled", stdout=StringIO())
        status = self.client.get(BASE + "jobs/").data
        self.assertTrue(status["worker_deployed"])
        self.assertEqual(status["worker_status"], "recent_runs_observed")
        self.assertIsNotNone(status["last_worker_run"])

    def test_scheduled_command_processes_one_real_job_and_emits_receipt(self):
        """Exercise the management-command entrypoint, not just the helper."""
        from io import StringIO
        from unittest.mock import patch
        from django.core.management import call_command
        from user_accounts.models import AuditLog
        goal_id = self.make_goal()
        self.assertEqual(self.enroll(goal_id).status_code, 201)

        flags = {
            "SYNC_ASSIST_DURABLE_WORKER_ENABLED": "true",
            "SYNC_ASSIST_DURABLE_SCHEDULED_ENABLED": "true",
        }
        with patch.dict("os.environ", flags):
            output = StringIO()
            call_command("sync_assist_queue_worker", "--once", "--scheduled",
                         "--max-jobs", "1", stdout=output)
            self.assertIn("Processed 1 job(s):", output.getvalue())

        job = SyncAssistJob.objects.get(owner=self.owner, goal_id=goal_id)
        self.assertEqual(job.state, SyncAssistJob.State.WAITING)
        self.assertIsNotNone(job.last_receipt_id)
        receipts = AuditLog.objects.filter(actor=self.owner, action="sync_assist.workday.worker_receipt")
        self.assertEqual(receipts.count(), 1)
        self.assertEqual(str(job.last_receipt_id), receipts.first().metadata["receipt_id"])
        self.assertEqual(receipts.first().metadata["external_actions"], 0)
        self.assertEqual(receipts.first().metadata["messages_sent"], 0)
        self.assertEqual(receipts.first().metadata["provider_requests"], 0)
        self.assertEqual(
            AuditLog.objects.filter(actor=self.owner, action="sync_assist.queue.worker_tick").count(), 1
        )

        # Idempotency: a second scheduled run cannot generate a second receipt.
        with patch.dict("os.environ", flags):
            output = StringIO()
            call_command("sync_assist_queue_worker", "--once", "--scheduled",
                         "--max-jobs", "1", stdout=output)
            self.assertIn("Processed 0 job(s): []", output.getvalue())
        self.assertEqual(receipts.count(), 1)

        # Owner must still attest the result; scheduling never self-approves.
        step = next(g for g in self.client.get(BASE).data["goals"] if g["id"] == goal_id)["steps"][0]
        self.assertEqual(step["status"], "PLANNED")
        self.assertEqual(step["worker_receipt"]["status"], "BLOCKED")
        self.assertEqual(self.client.get(BASE + "jobs/").data["jobs"][0]["state"], "WAITING")

    def test_scheduled_worker_refuses_unapproved_public_research(self):
        from io import StringIO
        from unittest.mock import patch
        from django.core.management import call_command
        from user_accounts.models import AuditLog
        external_id = self.make_goal("PUBLIC_SEARCH")
        self.assertEqual(self.enroll(external_id).status_code, 400)
        with patch.dict("os.environ", {
            "SYNC_ASSIST_DURABLE_WORKER_ENABLED": "true",
            "SYNC_ASSIST_DURABLE_SCHEDULED_ENABLED": "true",
            "SYNC_ASSIST_LIVE_RESEARCH_ENABLED": "true",
        }):
            call_command("sync_assist_queue_worker", "--once", "--scheduled",
                         stdout=StringIO())
        self.assertFalse(SyncAssistJob.objects.filter(owner=self.owner).exists())
        self.assertFalse(AuditLog.objects.filter(
            actor=self.owner, action="sync_assist.workday.worker_receipt"
        ).exists())
