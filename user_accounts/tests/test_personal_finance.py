from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase

from user_accounts.models import User
from user_accounts.models.personal_finance import (
    FinanceAccount,
    FinanceBudget,
    FinanceLiability,
    FinanceObligation,
    FinanceTransaction,
)
from user_accounts.services.finance_intelligence import infer_recurring_obligations


class PersonalFinanceFoundationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="finance-test", email="finance-test@example.com", password="test-password-123")
        self.client.force_authenticate(self.user)

    def test_dashboard_combines_connected_and_manual_finance_records(self):
        checking = FinanceAccount.objects.create(user=self.user, name="Checking", kind=FinanceAccount.Kind.CHECKING, current_balance=Decimal("2500.00"), is_manual=False)
        card = FinanceAccount.objects.create(user=self.user, name="Visa", kind=FinanceAccount.Kind.CREDIT_CARD, current_balance=Decimal("1000.00"), credit_limit=Decimal("5000.00"), is_manual=False)
        FinanceLiability.objects.create(user=self.user, account=card, name="Visa", kind=FinanceLiability.Kind.CREDIT_CARD, outstanding_balance=Decimal("1000.00"), minimum_payment=Decimal("55.00"))
        FinanceObligation.objects.create(user=self.user, linked_account=checking, name="Power", category=FinanceObligation.Category.UTILITIES, expected_amount=Decimal("180.00"), is_manual=True)
        response = self.client.get("/api/v1/personal-finance/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.data["net_position"]["cash"]), Decimal("2500.00"))
        self.assertEqual(Decimal(response.data["net_position"]["debt"]), Decimal("1000.00"))
        self.assertEqual(response.data["credit"]["utilization_percent"], 20.0)

    def test_user_cannot_see_another_users_accounts(self):
        other = User.objects.create_user(username="other-finance", email="other-finance@example.com", password="test-password-123")
        FinanceAccount.objects.create(user=other, name="Private", kind=FinanceAccount.Kind.CHECKING)
        response = self.client.get("/api/v1/personal-finance/accounts/")
        self.assertEqual(response.status_code, 200)
        payload = response.data
        accounts = payload.get("results", []) if isinstance(payload, dict) else payload
        self.assertEqual(len(accounts), 0)

    def test_recurring_transactions_create_inferred_obligation(self):
        account = FinanceAccount.objects.create(user=self.user, name="Checking", kind=FinanceAccount.Kind.CHECKING, current_balance=Decimal("1500.00"))
        today = timezone.localdate()
        for index, days_ago in enumerate((60, 30, 0), start=1):
            FinanceTransaction.objects.create(user=self.user, account=account, provider_transaction_id=f"netflix-{index}", merchant_name="Netflix", description="Netflix subscription", amount=Decimal("19.99"), date=today - timedelta(days=days_ago), category_primary="ENTERTAINMENT")
        result = infer_recurring_obligations(self.user)
        self.assertEqual(result["created"], 1)
        obligation = FinanceObligation.objects.get(user=self.user, provider_stream_id__startswith="SYNC-INFERRED:")
        self.assertEqual(obligation.cadence, "MONTHLY")
        self.assertEqual(obligation.expected_amount, Decimal("19.99"))
        self.assertFalse(obligation.is_manual)

    def test_finance_decision_engine_returns_safe_spend_budgets_and_debt_order(self):
        checking = FinanceAccount.objects.create(user=self.user, name="Checking", kind=FinanceAccount.Kind.CHECKING, current_balance=Decimal("3000.00"))
        today = timezone.localdate()
        FinanceObligation.objects.create(user=self.user, linked_account=checking, name="Rent", category=FinanceObligation.Category.HOUSING, expected_amount=Decimal("1200.00"), next_due_date=today + timedelta(days=5))
        FinanceBudget.objects.create(user=self.user, name="Dining", category="FOOD_AND_DRINK", monthly_limit=Decimal("400.00"))
        FinanceTransaction.objects.create(user=self.user, account=checking, provider_transaction_id="food-1", merchant_name="Restaurant", amount=Decimal("125.00"), date=today, category_primary="FOOD_AND_DRINK")
        FinanceLiability.objects.create(user=self.user, name="Card A", kind=FinanceLiability.Kind.CREDIT_CARD, outstanding_balance=Decimal("2000.00"), apr=Decimal("24.99"), minimum_payment=Decimal("60.00"))
        FinanceLiability.objects.create(user=self.user, name="Card B", kind=FinanceLiability.Kind.CREDIT_CARD, outstanding_balance=Decimal("500.00"), apr=Decimal("12.00"), minimum_payment=Decimal("30.00"))

        response = self.client.get("/api/v1/personal-finance/automation/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.data["summary"]["safe_to_spend_now"]), Decimal("1800.00"))
        self.assertEqual(Decimal(response.data["budgets"][0]["remaining"]), Decimal("275.00"))
        self.assertEqual(response.data["debt_strategy"]["avalanche"][0]["name"], "Card A")
        self.assertEqual(response.data["debt_strategy"]["snowball"][0]["name"], "Card B")
        self.assertIn("actions", response.data)

    def test_budget_api_is_user_scoped(self):
        FinanceBudget.objects.create(user=self.user, name="Dining", category="FOOD_AND_DRINK", monthly_limit=Decimal("500.00"))
        other = User.objects.create_user(username="budget-other", email="budget-other@example.com", password="test-password-123")
        FinanceBudget.objects.create(user=other, name="Private", category="PRIVATE", monthly_limit=Decimal("999.00"))
        response = self.client.get("/api/v1/personal-finance/budgets/")
        self.assertEqual(response.status_code, 200)
        payload = response.data
        budgets = payload.get("results", []) if isinstance(payload, dict) else payload
        self.assertEqual(len(budgets), 1)
        self.assertEqual(budgets[0]["name"], "Dining")
