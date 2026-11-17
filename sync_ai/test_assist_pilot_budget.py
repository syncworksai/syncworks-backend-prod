"""Budget tests: all employees share one $10 pilot allowance."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from .assist_pilot_budget import PilotBudgetExceeded, reserve_paid_tool, snapshot


class SharedPilotBudgetTests(TestCase):
    def setUp(self):
        model = get_user_model()
        self.owner = model.objects.create_user(email="pilot-budget-test@example.com", password="pass1234")

    def test_default_budget_includes_all_roles_and_untracked_hosting_warning(self):
        data = snapshot(self.owner)
        self.assertEqual(data["limit_usd"], "10.00")
        self.assertEqual(data["remaining_usd"], "10.00")
        self.assertIn("Render Cron/hosting", data["untracked_costs"])

    def test_two_employee_roles_share_the_same_cap(self):
        first = reserve_paid_tool(self.owner, role="RESEARCH_ANALYST", provider="fake-test", operation_key="research-001", max_usd="6.50")
        self.assertTrue(first["created"])
        other = reserve_paid_tool(self.owner, role="MARKETING_MANAGER", provider="fake-test", operation_key="marketing-001", max_usd="3.50")
        self.assertTrue(other["created"])
        balance = snapshot(self.owner)
        self.assertEqual(balance["reserved_usd"], "10.00")
        self.assertEqual(balance["remaining_usd"], "0.00")
        self.assertEqual(balance["status"], "exhausted")
        self.assertEqual(balance["by_role"]["RESEARCH_ANALYST"], "6.50")
        self.assertEqual(balance["by_role"]["MARKETING_MANAGER"], "3.50")
        with self.assertRaises(PilotBudgetExceeded):
            reserve_paid_tool(self.owner, role="CHIEF_OF_STAFF", provider="fake-test", operation_key="chief-001", max_usd="0.01")
        self.assertEqual(snapshot(self.owner)["reserved_usd"], "10.00")

    def test_retries_use_single_reservation_and_cannot_change_cost(self):
        kwargs = {"role": "SALES_MANAGER", "provider": "fake-test", "operation_key": "outreach-001", "max_usd": "0.15"}
        first = reserve_paid_tool(self.owner, **kwargs)
        again = reserve_paid_tool(self.owner, **kwargs)
        self.assertEqual(first["reservation_id"], again["reservation_id"])
        self.assertFalse(again["created"])
        self.assertEqual(snapshot(self.owner)["reserved_usd"], "0.15")
        with self.assertRaises(ValueError):
            reserve_paid_tool(self.owner, **{**kwargs, "max_usd": "0.20"})

    def test_rejects_bad_cost_and_unknown_agent(self):
        for value in ("-1", "NaN", "Infinity", "0", "0.001", "bad"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                reserve_paid_tool(self.owner, role="RESEARCH_ANALYST", provider="fake-test", operation_key="bad-cost-001", max_usd=value)
        with self.assertRaises(ValueError):
            reserve_paid_tool(self.owner, role="UNKNOWN", provider="fake-test", operation_key="unknown-001", max_usd=Decimal("1.00"))

    def test_budget_is_isolated_by_owner(self):
        other = get_user_model().objects.create_user(email="separate-budget@example.com", password="pass1234")
        reserve_paid_tool(self.owner, role="RESEARCH_ANALYST", provider="fake-test", operation_key="owner-001", max_usd="10.00")
        self.assertEqual(snapshot(other)["remaining_usd"], "10.00")
