from unittest import TestCase
from .employee_onboarding import MILESTONES, onboarding_plan, escalation_route

class EmployeeOnboardingTests(TestCase):
    def test_empty(self):
        plan = onboarding_plan([])
        self.assertEqual(plan["next_step"]["key"], "workspace_verified")
        self.assertFalse(plan["ready_for_tenant_activation"])

    def test_gate(self):
        verified = [m.key for m in MILESTONES]
        self.assertTrue(onboarding_plan(verified)["ready_for_tenant_activation"])
        self.assertFalse(onboarding_plan(verified, ["Missing deposit evidence"])["ready_for_tenant_activation"])
        self.assertFalse(onboarding_plan(verified[:-1])["ready_for_tenant_activation"])

    def test_escalation(self):
        self.assertEqual(escalation_route("missing_statement"), "AUTHORIZED_RECORD_PROVIDER")
        self.assertEqual(escalation_route("unknown"), "OWNER_OR_SYDNEY_REVIEW")
