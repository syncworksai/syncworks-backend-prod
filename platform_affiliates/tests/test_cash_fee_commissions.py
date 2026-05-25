from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from platform_affiliates.choices import RevenueSource
from platform_affiliates.models import (
    AffiliateCommissionLedger,
    AffiliatePartner,
)
from platform_affiliates.services.attribution_service import (
    assign_business_to_affiliate,
)
from platform_affiliates.services.cash_fee_commission_service import (
    record_cash_fee_invoice_commission,
)
from user_accounts.models import Business, CashFeeInvoice


User = get_user_model()


class AffiliateCashFeeCommissionTests(TestCase):
    def setUp(self):
        self.god_user = User.objects.create_user(
            username="godmode1",
            email="jacoblord7@outlook.com",
            password="testpass123",
            first_name="Jacob",
            last_name="Lord",
            is_staff=True,
        )

        self.owner = User.objects.create_user(
            username="owner1",
            email="owner@example.com",
            password="testpass123",
            first_name="Owner",
            last_name="One",
        )

        self.business = Business.objects.create(
            owner=self.owner,
            name="Test Plumbing LLC",
            business_email="owner@example.com",
            owner_name="Owner One",
        )

        self.affiliate = AffiliatePartner.objects.create(
            name="Affiliate One",
            email="affiliate@example.com",
            code="SWSC01",
            status="ACTIVE",
        )

        assign_business_to_affiliate(
            business=self.business,
            affiliate=self.affiliate,
            actor=self.god_user,
            reason="Cash fee commission test",
        )

    def token_client(self, user):
        token, _ = Token.objects.get_or_create(user=user)

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        return client

    def make_cash_fee_invoice(self, *, status="OPEN", amount_cents=5000):
        inv = CashFeeInvoice.objects.create(
            business=self.business,
            status=status,
            amount_cents=amount_cents,
            period_start=timezone.localdate().replace(day=1),
            period_end=timezone.localdate(),
            due_date=timezone.localdate(),
            memo="Cash GMV platform fee",
            created_by=self.god_user,
        )

        if status == CashFeeInvoice.Status.PAID:
            inv.paid_at = timezone.now()
            inv.save(update_fields=["paid_at", "updated_at"])

        return inv

    def test_paid_cash_fee_invoice_creates_affiliate_commission(self):
        inv = self.make_cash_fee_invoice(
            status=CashFeeInvoice.Status.PAID,
            amount_cents=5000,
        )

        commission = record_cash_fee_invoice_commission(inv)

        self.assertIsNotNone(commission)

        self.assertEqual(
            commission.revenue_source,
            RevenueSource.PLATFORM_FEE,
        )

        self.assertEqual(
            commission.net_syncworks_revenue_amount,
            Decimal("50.00"),
        )

        self.assertEqual(
            commission.commission_amount,
            Decimal("5.00"),
        )

        self.assertEqual(
            commission.source_reference,
            f"cash_fee_invoice:{inv.id}:platform_fee",
        )

    def test_cash_fee_commission_is_duplicate_safe(self):
        inv = self.make_cash_fee_invoice(
            status=CashFeeInvoice.Status.PAID,
            amount_cents=5000,
        )

        first = record_cash_fee_invoice_commission(inv)
        second = record_cash_fee_invoice_commission(inv)

        self.assertEqual(first.id, second.id)

        self.assertEqual(
            AffiliateCommissionLedger.objects.count(),
            1,
        )

    def test_open_cash_fee_invoice_does_not_create_commission(self):
        inv = self.make_cash_fee_invoice(
            status=CashFeeInvoice.Status.OPEN,
            amount_cents=5000,
        )

        commission = record_cash_fee_invoice_commission(inv)

        self.assertIsNone(commission)

        self.assertEqual(
            AffiliateCommissionLedger.objects.count(),
            0,
        )

    def test_mark_paid_endpoint_creates_affiliate_commission(self):
        inv = self.make_cash_fee_invoice(
            status=CashFeeInvoice.Status.OPEN,
            amount_cents=5000,
        )

        client = self.token_client(self.god_user)

        response = client.post(
            f"/api/v1/cash-fee-invoices/{inv.id}/mark-paid/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            AffiliateCommissionLedger.objects.count(),
            1,
        )

        commission = AffiliateCommissionLedger.objects.first()

        self.assertEqual(
            commission.net_syncworks_revenue_amount,
            Decimal("50.00"),
        )

        self.assertEqual(
            commission.commission_amount,
            Decimal("5.00"),
        )