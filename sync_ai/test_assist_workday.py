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
        self.assertTrue(response.data["execution_enabled"])
        self.assertFalse(response.data["background_execution_verified"])
        self.assertFalse(response.data["outbound_execution_enabled"])
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

    def test_internal_execution_produces_scoped_evidence_and_no_send(self):
        self.client.force_authenticate(self.owner)
        prospect = self.client.post("/api/v1/sync-ai/assist/pilot/growth/prospects/", {
            "company": "Local Example Services", "niche": "home_services",
            "website": "https://example.org", "observation": "A public service website.",
            "channel": "EMAIL",
        }, format="json")
        self.assertEqual(prospect.status_code, 201)
        goal = self.client.post(BASE, {
            "goal": "Research and draft outreach",
            "steps": [
                {"role": "RESEARCH_ANALYST", "task": "Report on explicitly entered companies"},
                {"role": "SALES_MANAGER", "task": "Prepare reviewed drafts"},
                {"role": "CHIEF_OF_STAFF", "task": "Summarize confirmed work"},
            ],
        }, format="json").data["goals"][0]
        url = BASE + goal["id"] + "/run/"
        first = self.client.post(url)
        self.assertEqual(first.status_code, 200)
        receipt = first.data["last_execution"]
        self.assertEqual(receipt["role"], "RESEARCH_ANALYST")
        self.assertEqual(receipt["status"], "AWAITING_APPROVAL")
        self.assertEqual(receipt["external_actions"], 0)
        self.assertEqual(receipt["model_calls"], 0)
        self.assertEqual(receipt["output"][0]["provenance"], "owner_entered_unverified")
        self.assertEqual(receipt["sources"][0]["type"], "syncworks_audit_event")
        # No duplicate run while research awaits owner review.
        self.assertEqual(self.client.post(url).status_code, 409)  # sales waits for approved research
        research_id = goal["steps"][0]["id"]
        confirmation = self.client.post(BASE + goal["id"] + "/steps/" + research_id + "/", {
            "status": "COMPLETED", "owner_attested": True,
            "evidence": "I checked this prospect report against my own records.",
        }, format="json")
        self.assertEqual(confirmation.status_code, 200)
        sales = self.client.post(url)
        self.assertEqual(sales.status_code, 200)
        self.assertEqual(sales.data["last_execution"]["role"], "SALES_MANAGER")
        self.assertFalse(sales.data["last_execution"]["output"][0]["sent"])
        self.assertEqual(sales.data["last_execution"]["messages_sent"], 0)
        self.assertEqual(
            AuditLog.objects.filter(actor=self.owner, action="sync_assist.workday.worker_receipt").count(), 2
        )

    def test_internal_execution_requires_pilot_and_source_evidence(self):
        self.client.force_authenticate(self.owner)
        goal = self._create().data["goals"][0]
        url = BASE + goal["id"] + "/run/"
        blocked = self.client.post(url)
        self.assertEqual(blocked.status_code, 200)
        self.assertEqual(blocked.data["last_execution"]["status"], "BLOCKED")
        self.assertEqual(blocked.data["last_execution"]["output"], [])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(url).status_code, 403)

    def test_public_search_is_opt_in_and_disabled_by_default(self):
        from unittest.mock import patch
        self.client.force_authenticate(self.owner)
        payload = {
            "goal": "Find listed service companies",
            "steps": [{"role": "RESEARCH_ANALYST", "task": "Find public references"}],
            "source_mode": "PUBLIC_SEARCH",
            "public_search_query": "property management companies Alabama",
        }
        self.assertEqual(self.client.post(BASE, payload, format="json").status_code, 400)
        payload["allow_external_search"] = True
        created = self.client.post(BASE, payload, format="json")
        self.assertEqual(created.status_code, 201)
        goal = created.data["goals"][0]
        self.assertEqual(goal["source_mode"], "PUBLIC_SEARCH")
        with patch.dict("os.environ", {"SYNC_ASSIST_LIVE_RESEARCH_ENABLED": "false"}):
            blocked = self.client.post(BASE + goal["id"] + "/run/")
        self.assertEqual(blocked.status_code, 200)
        self.assertEqual(blocked.data["last_execution"]["status"], "BLOCKED")

    def test_public_search_receipt_preserves_provider_sources_without_sending(self):
        from unittest.mock import Mock, patch
        self.client.force_authenticate(self.owner)
        payload = {
            "goal": "Research publicly listed businesses",
            "steps": [{"role": "RESEARCH_ANALYST", "task": "Collect public references"}],
            "source_mode": "PUBLIC_SEARCH",
            "public_search_query": "commercial property managers Alabama",
            "allow_external_search": True,
        }
        goal = self.client.post(BASE, payload, format="json").data["goals"][0]
        provider_response = Mock()
        provider_response.json.return_value = {"organic": [
            {"title": "Example Property Manager",
             "link": "https://example.org/",
             "snippet": "A publicly indexed business listing"},
        ]}
        with patch.dict("os.environ", {
            "SYNC_ASSIST_LIVE_RESEARCH_ENABLED": "true",
            "SERPER_API_KEY": "placeholder-for-test",
        }), patch("sync_ai.assist_public_search.requests.post", return_value=provider_response):
            run = self.client.post(BASE + goal["id"] + "/run/")
        self.assertEqual(run.status_code, 200)
        receipt = run.data["last_execution"]
        self.assertEqual(receipt["status"], "AWAITING_APPROVAL")
        self.assertEqual(receipt["sources"][0]["url"], "https://example.org/")
        self.assertFalse(receipt["output"][0]["qualified"])
        self.assertEqual(receipt["messages_sent"], 0)
        self.assertEqual(receipt["external_actions"], 0)
