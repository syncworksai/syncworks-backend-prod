"""Regression tests for owner-only employee budgets and shared spending alerts."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase
from user_accounts.models import AuditLog

from .assist_pilot_budget import PilotBudgetExceeded, reserve_paid_tool, snapshot
from .assist_budget_policy import configure_role_limit

BASE = "/api/v1/sync-ai/assist/pilot/budget/"


class RoleBudgetTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="role-cap-owner", email="role-cap@example.com", password="testpass123"
        )

    def test_employee_cap_blocks_without_raising_shared_ceiling(self):
        configure_role_limit(self.owner, role="RESEARCH_ANALYST", limit_usd="2.00")
        reserve_paid_tool(self.owner, role="RESEARCH_ANALYST", provider="fake",
                          operation_key="research-10", max_usd="1.50")
        with self.assertRaises(PilotBudgetExceeded):
            reserve_paid_tool(self.owner, role="RESEARCH_ANALYST", provider="fake",
                              operation_key="research-11", max_usd="0.51")
        reserve_paid_tool(self.owner, role="SALES_MANAGER", provider="fake",
                          operation_key="sales-001", max_usd="8.50")
        data = snapshot(self.owner)
        self.assertEqual(data["reserved_usd"], "10.00")
        self.assertEqual(data["employee_budgets"]["RESEARCH_ANALYST"]["remaining_usd"], "0.50")
        self.assertEqual([a["threshold_percent"] for a in data["alerts"]], [75, 90, 100])
        self.assertIsNone(data["actual_provider_cost_usd"])

    def test_threshold_notifications_are_durable_and_not_duplicated(self):
        reserve_paid_tool(self.owner, role="SALES_MANAGER", provider="fake",
                          operation_key="sales-001", max_usd="7.50")
        reserve_paid_tool(self.owner, role="SALES_MANAGER", provider="fake",
                          operation_key="sales-002", max_usd="1.50")
        reserve_paid_tool(self.owner, role="SALES_MANAGER", provider="fake",
                          operation_key="sales-003", max_usd="1.00")
        reserve_paid_tool(self.owner, role="SALES_MANAGER", provider="fake",
                          operation_key="sales-003", max_usd="1.00")
        self.assertEqual(list(AuditLog.objects.filter(
            actor=self.owner, action="sync_assist.budget.threshold_alert"
        ).order_by("id").values_list("metadata__threshold_percent", flat=True)), [75, 90, 100])

    def test_invalid_or_lower_than_reserved_role_limit_rejected(self):
        reserve_paid_tool(self.owner, role="MARKETING_MANAGER", provider="fake",
                          operation_key="market-001", max_usd="2.00")
        for limit in ("-1", "10.01", "NaN", "2.001", "1.99"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                configure_role_limit(self.owner, role="MARKETING_MANAGER", limit_usd=limit)
        configure_role_limit(self.owner, role="MARKETING_MANAGER", limit_usd="2.00")
        with self.assertRaises(PilotBudgetExceeded):
            reserve_paid_tool(self.owner, role="MARKETING_MANAGER", provider="fake",
                              operation_key="market-002", max_usd="0.01")


@override_settings(REST_FRAMEWORK={
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
})
class BudgetApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            username="cost-pilot", email="jacoblord7@outlook.com", password="testpass123")
        self.other = User.objects.create_user(
            username="cost-non-pilot", email="not-pilot@example.com", password="testpass123")

    def test_pilot_can_view_and_change_only_own_role_limits(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.get(BASE).data["limit_usd"], "10.00")
        response = self.client.post(BASE, {"role": "SALES_MANAGER", "limit_usd": "3.00"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["employee_budgets"]["SALES_MANAGER"]["limit_usd"], "3.00")
        self.assertEqual(self.client.post(BASE, {
            "role": "SALES_MANAGER", "limit_usd": "50.00"}, format="json").status_code, 400)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(BASE).status_code, 403)
        self.assertEqual(self.client.post(BASE, {
            "role": "SALES_MANAGER", "limit_usd": "10.00"}, format="json").status_code, 403)
