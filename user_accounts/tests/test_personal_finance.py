from decimal import Decimal

from rest_framework.test import APITestCase

from user_accounts.models import User
from user_accounts.models.personal_finance import FinanceAccount, FinanceLiability, FinanceObligation


class PersonalFinanceFoundationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="finance-test",
            email="finance-test@example.com",
            password="test-password-123",
        )
        self.client.force_authenticate(self.user)

    def test_dashboard_combines_connected_and_manual_finance_records(self):
        checking = FinanceAccount.objects.create(
            user=self.user,
            name="Checking",
            kind=FinanceAccount.Kind.CHECKING,
            current_balance=Decimal("2500.00"),
            is_manual=False,
        )
        card = FinanceAccount.objects.create(
            user=self.user,
            name="Visa",
            kind=FinanceAccount.Kind.CREDIT_CARD,
            current_balance=Decimal("1000.00"),
            credit_limit=Decimal("5000.00"),
            is_manual=False,
        )
        FinanceLiability.objects.create(
            user=self.user,
            account=card,
            name="Visa",
            kind=FinanceLiability.Kind.CREDIT_CARD,
            outstanding_balance=Decimal("1000.00"),
            minimum_payment=Decimal("55.00"),
        )
        FinanceObligation.objects.create(
            user=self.user,
            linked_account=checking,
            name="Power",
            category=FinanceObligation.Category.UTILITIES,
            expected_amount=Decimal("180.00"),
            is_manual=True,
        )

        response = self.client.get("/api/v1/personal-finance/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.data["net_position"]["cash"]), Decimal("2500.00"))
        self.assertEqual(Decimal(response.data["net_position"]["debt"]), Decimal("1000.00"))
        self.assertEqual(response.data["credit"]["utilization_percent"], 20.0)

    def test_user_cannot_see_another_users_accounts(self):
        other = User.objects.create_user(
            username="other-finance",
            email="other-finance@example.com",
            password="test-password-123",
        )
        FinanceAccount.objects.create(user=other, name="Private", kind=FinanceAccount.Kind.CHECKING)
        response = self.client.get("/api/v1/personal-finance/accounts/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 0)
