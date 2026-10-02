from decimal import Decimal

from rest_framework.test import APITestCase

from user_accounts.models import User
from user_accounts.models.personal_finance import (
    FinanceAccount,
    FinanceIncomeSource,
    FinanceLiability,
    FinanceObligation,
)


class FinanceCashFlowTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="cashflow-test", email="cashflow-test@example.com", password="test-password-123")
        self.client.force_authenticate(self.user)

    def test_dashboard_exposes_planned_inflow_and_outflow(self):
        FinanceIncomeSource.objects.create(
            user=self.user,
            name="Weekly pay",
            kind=FinanceIncomeSource.Kind.PAYCHECK,
            amount=Decimal("1000.00"),
            cadence=FinanceIncomeSource.Cadence.WEEKLY,
        )
        FinanceObligation.objects.create(
            user=self.user,
            name="Phone",
            category=FinanceObligation.Category.PHONE,
            expected_amount=Decimal("100.00"),
            cadence="MONTHLY",
        )
        FinanceLiability.objects.create(
            user=self.user,
            name="Auto loan",
            kind=FinanceLiability.Kind.AUTO_LOAN,
            outstanding_balance=Decimal("12000.00"),
            minimum_payment=Decimal("400.00"),
        )

        response = self.client.get("/api/v1/personal-finance/dashboard/")
        self.assertEqual(response.status_code, 200)
        planned = response.data["planned_month"]
        self.assertEqual(Decimal(str(planned["expected_income"])), Decimal("4333.30"))
        self.assertEqual(Decimal(str(planned["expected_bills"])), Decimal("100.00"))
        self.assertEqual(Decimal(str(planned["known_debt_minimums"])), Decimal("400.00"))
        self.assertEqual(Decimal(str(planned["expected_outflow"])), Decimal("500.00"))
        self.assertEqual(Decimal(str(planned["expected_cash_flow"])), Decimal("3833.30"))

    def test_closed_cards_do_not_inflate_credit_utilization(self):
        FinanceAccount.objects.create(
            user=self.user,
            name="Open card",
            kind=FinanceAccount.Kind.CREDIT_CARD,
            current_balance=Decimal("500.00"),
            credit_limit=Decimal("1000.00"),
            is_manual=True,
            metadata={"account_status": "OPEN"},
        )
        FinanceAccount.objects.create(
            user=self.user,
            name="Closed card",
            kind=FinanceAccount.Kind.CREDIT_CARD,
            current_balance=Decimal("5000.00"),
            credit_limit=Decimal("1000.00"),
            is_manual=True,
            metadata={"account_status": "CLOSED"},
        )

        response = self.client.get("/api/v1/personal-finance/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["credit"]["utilization_percent"], 50.0)
        self.assertEqual(response.data["credit"]["active_revolving_accounts"], 1)

    def test_income_sources_are_user_scoped(self):
        other = User.objects.create_user(username="cashflow-other", email="cashflow-other@example.com", password="test-password-123")
        FinanceIncomeSource.objects.create(user=self.user, name="Mine", amount=Decimal("100.00"))
        FinanceIncomeSource.objects.create(user=other, name="Private", amount=Decimal("999.00"))
        response = self.client.get("/api/v1/personal-finance/income-sources/")
        self.assertEqual(response.status_code, 200)
        payload = response.data
        rows = payload.get("results", []) if isinstance(payload, dict) else payload
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Mine")
