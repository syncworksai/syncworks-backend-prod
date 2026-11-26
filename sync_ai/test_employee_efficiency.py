from unittest import TestCase
from .employee_efficiency import budget_decision, plan_portfolio_actions

class EmployeeEfficiencyTests(TestCase):
    def test_shared_ceiling(self):
        self.assertTrue(budget_decision("8", ".5", ".5").allowed)
        self.assertFalse(budget_decision("8", ".5", ".51").allowed)
        self.assertTrue(budget_decision("9", ".5", ".5", emergency=True).allowed)
        self.assertFalse(budget_decision("9", ".5", ".51", emergency=True).allowed)

    def test_invalid_cost(self):
        for value in (None, "NaN", "Infinity", "-1", "0"):
            self.assertFalse(budget_decision("0", "0", value).allowed)

    def test_plan(self):
        props = [{"id": 7, "operations": {"overdue_projects": 2,
                  "recorded_leases_ending_within_60_days": 1}, "requires_review": True}]
        actions = plan_portfolio_actions(props)
        self.assertEqual(len(actions), 3)
        self.assertEqual(len({a["dedupe_key"] for a in actions}), 3)
        self.assertTrue(all(a["mode"] == "INTERNAL_REVIEW" for a in actions))
        self.assertEqual(plan_portfolio_actions([{"id": 8}]), [])
