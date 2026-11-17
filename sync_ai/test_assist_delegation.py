"""Victoria delegation: idempotent enrollment and owner-approved handoffs."""
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from user_accounts.models import AuditLog, SyncAssistJob
from .assist_job_queue import run_batch
from .assist_workday_views import CREATED, WORKED

BASE = "/api/v1/sync-ai/assist/pilot/"


@override_settings(REST_FRAMEWORK={
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
})
class VictoriaDelegationTests(APITestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(
            username="victoria-delegate", email="jacoblord7@outlook.com", password="testpass123")
        self.other = users.objects.create_user(
            username="victoria-outsider", email="outsider@example.com", password="testpass123")
        self.client.force_authenticate(self.owner)

    def payload(self, request_id=None):
        return {"template": "PROSPECT_TO_OUTREACH_REVIEW",
                "request_id": str(request_id or uuid4()),
                "allow_background_internal": True}

    def test_permission_consent_and_idempotency(self):
        data = self.payload()
        self.assertEqual(self.client.post(BASE + "delegate/", {
            **data, "allow_background_internal": False}, format="json").status_code, 400)
        first = self.client.post(BASE + "delegate/", data, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.data["job"]["state"], "QUEUED")
        repeated = self.client.post(BASE + "delegate/", data, format="json")
        self.assertEqual(repeated.status_code, 200)
        self.assertFalse(repeated.data["created"])
        self.assertEqual(repeated.data["goal_id"], first.data["goal_id"])
        self.assertEqual(AuditLog.objects.filter(actor=self.owner, action=CREATED).count(), 1)
        self.assertEqual(SyncAssistJob.objects.filter(owner=self.owner).count(), 1)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(BASE + "delegate/", self.payload(), format="json").status_code, 403)

    def test_existing_prospects_produce_research_then_approval_gated_sales_and_victoria(self):
        response = self.client.post(BASE + "growth/prospects/", {
            "company": "Sample Heating", "niche": "home_services",
            "website": "https://example.org", "channel": "EMAIL",
            "draft": "Hello, would you be interested in a brief SyncWorks introduction?"
        }, format="json")
        self.assertEqual(response.status_code, 201)
        created = self.client.post(BASE + "delegate/", self.payload(), format="json")
        self.assertEqual(created.status_code, 201)
        goal_id = created.data["goal_id"]
        self.assertEqual(run_batch(limit=1), ["WAITING"])
        goal = next(x for x in self.client.get(BASE + "workday/").data["goals"] if x["id"] == goal_id)
        first_step = goal["steps"][0]
        self.assertEqual(first_step["role"], "RESEARCH_ANALYST")
        self.assertEqual(first_step["worker_receipt"]["status"], "AWAITING_APPROVAL")
        self.assertEqual(first_step["worker_receipt"]["model_calls"], 0)
        self.assertEqual(first_step["worker_receipt"]["messages_sent"], 0)
        self.assertEqual(run_batch(limit=1), [])
        for index, role in enumerate(["RESEARCH_ANALYST", "SALES_MANAGER", "CHIEF_OF_STAFF"]):
            goal = next(x for x in self.client.get(BASE + "workday/").data["goals"] if x["id"] == goal_id)
            step = goal["steps"][index]
            self.assertEqual(step["role"], role)
            self.assertEqual(step["worker_receipt"]["status"], "AWAITING_APPROVAL")
            response = self.client.post(
                BASE + f"workday/{goal_id}/steps/{step['id']}/",
                {"status": "COMPLETED", "owner_attested": True,
                 "evidence": "Reviewed the specialist output and verified the source details."},
                format="json")
            self.assertEqual(response.status_code, 200)
            if index < 2:
                self.assertEqual(run_batch(limit=1), ["WAITING"])
        self.assertEqual(SyncAssistJob.objects.get(owner=self.owner, goal_id=goal_id).state, "SUCCEEDED")
        self.assertEqual(AuditLog.objects.filter(actor=self.owner, action=WORKED).count(), 3)
        self.assertEqual(run_batch(limit=1), [])

    def test_no_prospects_stays_blocked_without_outbound_actions(self):
        created = self.client.post(BASE + "delegate/", self.payload(), format="json")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(run_batch(limit=1), ["WAITING"])
        goal = next(x for x in self.client.get(BASE + "workday/").data["goals"] if x["id"] == created.data["goal_id"])
        receipt = goal["steps"][0]["worker_receipt"]
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertEqual(receipt["external_actions"], 0)
        self.assertEqual(receipt["provider_requests"] if "provider_requests" in receipt else 0, 0)
