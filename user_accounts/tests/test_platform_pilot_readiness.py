from django.test import TestCase
from rest_framework.test import APIClient

from user_accounts.models.production_readiness import ProductionReadinessState
from user_accounts.models.user import User
from user_accounts.services.god_mode import FOUNDER_GOD_MODE_EMAIL
from user_accounts.viewsets.platform_pilot_readiness import GATES


URL = "/api/v1/platform/pilot-readiness/"


class FounderPilotReadinessTests(TestCase):
    def setUp(self):
        self.founder = User.objects.create_user(
            username="founder-pilot-readiness", email=FOUNDER_GOD_MODE_EMAIL, password="TestOnlyPassword123!"
        )
        self.other = User.objects.create_user(
            username="regular-pilot-readiness", email="regular@example.com", password="TestOnlyPassword123!"
        )
        self.client = APIClient()

    def test_default_all_not_tested_never_auto_passes(self):
        self.client.force_authenticate(self.founder)
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["summary"]["total"], len(GATES))
        self.assertEqual(r.data["summary"]["not_tested"], len(GATES))
        self.assertFalse(r.data["launch_ready"])
        self.assertFalse(ProductionReadinessState.objects.filter(key="PILOT_READINESS").exists())

    def test_only_founder_can_read_and_update(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(self.client.patch(URL, {
            "gate_id": "personal_signup", "status": "PASS",
            "evidence": "A genuine confirmation code and session were tested.",
        }, format="json").status_code, 403)
        self.client.force_authenticate(user=None)
        self.assertIn(self.client.get(URL).status_code, (401, 403))

    def test_saving_pass_requires_evidence_and_audit_history(self):
        self.client.force_authenticate(self.founder)
        self.assertEqual(self.client.patch(URL, {
            "gate_id": "personal_signup", "status": "PASS", "evidence": "ok",
        }, format="json").status_code, 400)
        self.assertEqual(self.client.patch(URL, {
            "gate_id": "made_up_gate", "status": "PASS",
            "evidence": "Unexpected user-supplied gate never accepted.",
        }, format="json").status_code, 400)
        self.assertEqual(self.client.patch(URL, {
            "gate_id": "personal_signup", "status": "WHATEVER",
        }, format="json").status_code, 400)
        r = self.client.patch(URL, {
            "gate_id": "personal_signup", "status": "PASS",
            "evidence": "Verified test inbox code and correct account session in browser.",
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["summary"]["passed"], 1)
        self.assertFalse(r.data["launch_ready"])
        self.assertEqual(r.data["recent_history"][0]["old_status"], "NOT_TESTED")
        self.assertEqual(r.data["recent_history"][0]["status"], "PASS")
        state = ProductionReadinessState.objects.get(key="PILOT_READINESS")
        self.assertEqual(state.updated_by, self.founder)
        self.assertTrue(state.certification["gates"]["personal_signup"]["evidence"])

        reload = self.client.get(URL)
        self.assertEqual(reload.data["summary"]["passed"], 1)
        reset = self.client.patch(URL, {
            "gate_id": "personal_signup", "status": "NOT_TESTED",
        }, format="json")
        self.assertEqual(reset.status_code, 200, reset.data)
        self.assertEqual(reset.data["summary"]["passed"], 0)
        self.assertEqual(reset.data["summary"]["not_tested"], len(GATES))
        self.assertEqual(reset.data["recent_history"][0]["old_status"], "PASS")
        self.assertEqual(reset.data["gates"][0]["evidence"], "")

    def test_blocked_or_failed_gate_prevents_launch_ready(self):
        self.client.force_authenticate(self.founder)
        self.client.patch(URL, {
            "gate_id": "stripe_sandbox", "status": "BLOCKED",
            "evidence": "Processor test payout and refund not yet reconciled.",
        }, format="json")
        r = self.client.get(URL)
        self.assertEqual(r.data["summary"]["blocked"], 1)
        self.assertFalse(r.data["launch_ready"])
        self.client.patch(URL, {
            "gate_id": "stripe_sandbox", "status": "FAIL",
            "evidence": "Refund test showed a mismatch with the local invoice ledger.",
        }, format="json")
        r = self.client.get(URL)
        self.assertEqual(r.data["summary"]["failed"], 1)
        self.assertFalse(r.data["launch_ready"])
