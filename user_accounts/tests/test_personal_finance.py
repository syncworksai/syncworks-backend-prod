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

    def test_plan_1_uses_small_high_interest_quick_win_then_avalanche(self):
        card_small = FinanceAccount.objects.create(
            user=self.user,
            name="Small High APR",
            kind=FinanceAccount.Kind.CREDIT_CARD,
            current_balance=Decimal("360.00"),
            credit_limit=Decimal("3600.00"),
            is_manual=True,
        )
        FinanceLiability.objects.create(
            user=self.user,
            account=card_small,
            name="Small High APR",
            kind=FinanceLiability.Kind.CREDIT_CARD,
            outstanding_balance=Decimal("360.00"),
            apr=Decimal("29.74"),
            minimum_payment=Decimal("35.00"),
            is_manual=True,
        )
        card_large = FinanceAccount.objects.create(
            user=self.user,
            name="Large High APR",
            kind=FinanceAccount.Kind.CREDIT_CARD,
            current_balance=Decimal("7800.00"),
            credit_limit=Decimal("10000.00"),
            is_manual=True,
        )
        FinanceLiability.objects.create(
            user=self.user,
            account=card_large,
            name="Large High APR",
            kind=FinanceLiability.Kind.CREDIT_CARD,
            outstanding_balance=Decimal("7800.00"),
            apr=Decimal("28.49"),
            minimum_payment=Decimal("240.00"),
            is_manual=True,
        )
        FinanceLiability.objects.create(
            user=self.user,
            name="Cash Flow Unlock",
            kind=FinanceLiability.Kind.PERSONAL_LOAN,
            outstanding_balance=Decimal("1103.69"),
            minimum_payment=Decimal("538.00"),
            is_manual=True,
        )

        response = self.client.get("/api/v1/personal-finance/automation/?extra_monthly=500")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["plan_1"]["first_target"]["name"], "Small High APR")
        self.assertEqual(Decimal(str(response.data["plan_1"]["extra_monthly"])), Decimal("500"))
        self.assertEqual(Decimal(str(response.data["plan_1"]["known_minimum_payments"])), Decimal("813.00"))
        self.assertEqual(response.data["plan_1"]["priority"][1]["name"], "Cash Flow Unlock")
        self.assertEqual(response.data["plan_1"]["priority"][2]["name"], "Large High APR")

    def test_manual_card_endpoint_creates_account_and_liability_together(self):
        response = self.client.post(
            "/api/v1/personal-finance/automation/manual-card/",
            {
                "name": "Promo Card",
                "balance": "11434.98",
                "credit_limit": "12000.00",
                "minimum_payment": "64.00",
                "next_payment_date": (timezone.localdate() + timedelta(days=7)).isoformat(),
                "apr": "0",
                "promo_apr": "0",
                "promo_apr_end_date": (timezone.localdate() + timedelta(days=365)).isoformat(),
                "account_status": "OPEN",
                "paid_this_cycle": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        account = FinanceAccount.objects.get(user=self.user, name="Promo Card")
        liability = FinanceLiability.objects.get(user=self.user, name="Promo Card")
        self.assertEqual(liability.account_id, account.id)
        self.assertEqual(account.credit_limit, Decimal("12000.00"))
        self.assertEqual(liability.metadata["account_status"], "OPEN")
        self.assertTrue(liability.metadata["paid_this_cycle"])
        self.assertIn("promo_apr_end_date", liability.metadata)

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
