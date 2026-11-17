from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from user_accounts.models import FreelanceSyntheticJob
from sync_ai.freelance_synthetic_queue import run_batch

ROOT = "/api/v1/sync-ai/freelance/pilot/synthetic-jobs/"

class FreelanceSyntheticQueueTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.founder = User.objects.create_user(username="founder-synthetic", email="jacoblord7@outlook.com", password="x")
        self.founder.email_verified = True
        self.founder.save(update_fields=["email_verified"])
        self.other = User.objects.create_user(username="other-synthetic", email="other@example.com", password="x")
        self.config = override_settings(FREELANCE_PILOT_USER_ID=str(self.founder.pk))
        self.config.enable()
        self.addCleanup(self.config.disable)
        self.client = APIClient()

    def test_requires_verified_pinned_identity_and_explicit_consent(self):
        self.assertEqual(self.client.get(ROOT).status_code, 401)
        self.client.force_authenticate(user=self.other)
        self.assertEqual(self.client.get(ROOT).status_code, 403)
        self.client.force_authenticate(user=self.founder)
        self.assertEqual(self.client.post(ROOT, {"row_count": 500}, format="json").status_code, 400)
        self.assertEqual(self.client.post(ROOT, {"row_count": 500, "consent_synthetic_only": True, "project_id": "a796db9d-4ae1-4749-ac6b-d8f8b140c9d4"}, format="json").status_code, 404)

    def test_durable_synthetic_workflow_and_owner_scoping(self):
        self.client.force_authenticate(user=self.founder)
        created = self.client.post(ROOT, {"row_count": 500, "seed": 42, "consent_synthetic_only": True}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        job_id = created.data["job"]["id"]
        self.assertEqual(created.data["job"]["state"], "QUEUED")
        self.assertEqual(self.client.get(ROOT + job_id + "/download/").status_code, 404)
        self.assertEqual(self.client.post(ROOT + job_id + "/", {"decision": "approve"}, format="json").status_code, 409)
        self.assertEqual(run_batch(limit=1), ["REVIEW"])
        persisted = FreelanceSyntheticJob.objects.get(pk=job_id)
        self.assertEqual(persisted.state, "REVIEW")
        self.assertEqual(persisted.result["source_rows"], 500)
        self.assertGreater(persisted.result["duplicates_removed"], 0)
        self.assertEqual(persisted.result["ai_provider_cost_cents"], 0)
        self.assertEqual(self.client.post(ROOT + job_id + "/", {"decision": "approve"}, format="json").status_code, 200)
        delivered = self.client.get(ROOT + job_id + "/download/")
        self.assertEqual(delivered.status_code, 200)
        self.assertTrue(delivered.data["synthetic_only"])
        import base64
        content = base64.b64decode(delivered.data["content_base64"])
        self.assertIn(b"example.invalid", content)
        self.client.force_authenticate(user=self.other)
        self.assertEqual(self.client.get(ROOT + job_id + "/").status_code, 403)
        self.assertEqual(self.client.get(ROOT + job_id + "/download/").status_code, 403)

    def test_cancel_before_worker_runs(self):
        self.client.force_authenticate(user=self.founder)
        created = self.client.post(ROOT, {"row_count": 12, "consent_synthetic_only": True}, format="json")
        key = created.data["job"]["id"]
        self.assertEqual(self.client.post(ROOT + key + "/", {"decision": "cancel"}, format="json").status_code, 200)
        self.assertEqual(run_batch(limit=1), [])
        self.assertEqual(FreelanceSyntheticJob.objects.get(pk=key).state, "CANCELLED")

    def test_limits(self):
        self.client.force_authenticate(user=self.founder)
        for bad_count in [0,1001,"not-a-number"]:
            self.assertEqual(self.client.post(ROOT, {"row_count": bad_count, "consent_synthetic_only": True}, format="json").status_code, 400)
