from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase

from user_accounts.models import User
from user_accounts.models.finance_payments import FinanceDebtPayment
from user_accounts.models.personal_finance import FinanceAccount, FinanceLiability


class FinanceDebtPaymentTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="finance-pay-test", email="finance-pay-test@example.com", password="test-password-123")
        self.client.force_authenticate(self.user)
        self.account = FinanceAccount.objects.create(
            user=self.user,
            name="Card",
            kind=FinanceAccount.Kind.CREDIT_CARD,
            current_balance=Decimal("1000.00"),
            credit_limit=Decimal("2000.00"),
            is_manual=True,
        )
        self.checking = FinanceAccount.objects.create(
            user=self.user,
            name="Checking",
            kind=FinanceAccount.Kind.CHECKING,
            current_balance=Decimal("1500.00"),
            is_manual=True,
        )
        self.liability = FinanceLiability.objects.create(
            user=self.user,
            account=self.account,
            name="Card",
            kind=FinanceLiability.Kind.CREDIT_CARD,
            outstanding_balance=Decimal("1000.00"),
            minimum_payment=Decimal("50.00"),
            next_payment_amount=Decimal("50.00"),
            apr=Decimal("24.0000"),
            is_manual=True,
        )

    def test_manual_payment_updates_balance_cash_and_plan(self):
        response = self.client.post(
            "/api/v1/personal-finance/debt-payments/",
            {
                "liability": self.liability.id,
                "amount": "200.00",
                "payment_date": timezone.localdate().isoformat(),
                "funding_account": self.checking.id,
                "notes": "Extra payment",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.liability.refresh_from_db()
        self.account.refresh_from_db()
        self.checking.refresh_from_db()
        self.assertEqual(self.liability.outstanding_balance, Decimal("800.00"))
        self.assertEqual(self.account.current_balance, Decimal("800.00"))
        self.assertEqual(self.checking.current_balance, Decimal("1300.00"))
        self.assertEqual(self.liability.last_payment_amount, Decimal("200.00"))
        self.assertEqual(self.liability.last_payment_date, timezone.localdate())
        self.assertTrue(self.liability.metadata["paid_this_cycle"])

        payment = FinanceDebtPayment.objects.get(user=self.user, liability=self.liability)
        self.assertEqual(payment.funding_account_id, self.checking.id)
        self.assertEqual(payment.balance_before, Decimal("1000.00"))
        self.assertEqual(payment.balance_after, Decimal("800.00"))
        self.assertEqual(payment.principal_amount, Decimal("200.00"))
        self.assertEqual(payment.estimated_interest_saved_next_30_days, Decimal("3.95"))

        plan = self.client.get("/api/v1/personal-finance/automation/")
        self.assertEqual(plan.status_code, 200)
        self.assertEqual(Decimal(str(plan.data["plan_1"]["total_debt"])), Decimal("800.00"))

        dashboard = self.client.get("/api/v1/personal-finance/dashboard/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(Decimal(str(dashboard.data["net_position"]["cash"])), Decimal("1300.00"))
        self.assertEqual(Decimal(str(dashboard.data["this_month"]["manual_debt_payments"])), Decimal("200.00"))
        self.assertEqual(Decimal(str(dashboard.data["this_month"]["remaining_debt_minimums"])), Decimal("0.00"))

    def test_payment_cannot_touch_another_users_debt(self):
        other = User.objects.create_user(username="finance-pay-other", email="finance-pay-other@example.com", password="test-password-123")
        other_debt = FinanceLiability.objects.create(
            user=other,
            name="Private debt",
            kind=FinanceLiability.Kind.CREDIT_CARD,
            outstanding_balance=Decimal("500.00"),
        )
        response = self.client.post(
            "/api/v1/personal-finance/debt-payments/",
            {"liability": other_debt.id, "amount": "50.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        other_debt.refresh_from_db()
        self.assertEqual(other_debt.outstanding_balance, Decimal("500.00"))

    def test_payment_history_is_user_scoped(self):
        self.client.post(
            "/api/v1/personal-finance/debt-payments/",
            {"liability": self.liability.id, "amount": "50.00"},
            format="json",
        )
        other = User.objects.create_user(username="finance-pay-list-other", email="finance-pay-list-other@example.com", password="test-password-123")
        other_debt = FinanceLiability.objects.create(user=other, name="Other", outstanding_balance=Decimal("100.00"))
        FinanceDebtPayment.objects.create(user=other, liability=other_debt, amount=Decimal("25.00"), payment_date=timezone.localdate())

        response = self.client.get("/api/v1/personal-finance/debt-payments/")
        self.assertEqual(response.status_code, 200)
        rows = response.data.get("results", []) if isinstance(response.data, dict) else response.data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["liability_name"], "Card")
