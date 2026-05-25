from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from platform_affiliates.choices import RevenueSource
from platform_affiliates.models import (
    AffiliateCommissionLedger,
    AffiliatePartner,
)
from platform_affiliates.services.attribution_service import (
    assign_business_to_affiliate,
)
from platform_affiliates.services.invoice_commission_service import (
    record_invoice_platform_fee_commission,
)
from user_accounts.models import Business
from user_accounts.models.billing import Invoice
from user_accounts.models.tickets import Ticket


User = get_user_model()


class AffiliateInvoiceCommissionTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="customer1",
            email="customer@example.com",
            password="testpass123",
            first_name="Customer",
            last_name="One",
        )

        self.god_user = User.objects.create_user(
            username="godmode1",
            email="jacoblord7@outlook.com",
            password="testpass123",
            first_name="Jacob",
            last_name="Lord",
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

        self.ticket = Ticket.objects.create(
            customer=self.customer,
            assigned_business=self.business,
            service_zip="36109",
            service_address="123 Main Street",
            status=Ticket.Status.COMPLETED,
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
            reason="Invoice commission test",
        )

    def test_paid_invoice_platform_fee_creates_affiliate_commission(self):
        invoice = Invoice.objects.create(
            ticket=self.ticket,
            title="Invoice Test",
            subtotal=Decimal("5000.00"),
            tax=Decimal("0.00"),
            total=Decimal("5000.00"),
            payment_method=Invoice.PaymentMethod.CARD,
        )

        invoice.mark_paid(method=Invoice.PaymentMethod.CARD)
        invoice.save()

        commission = record_invoice_platform_fee_commission(invoice)

        self.assertIsNotNone(commission)

        self.assertEqual(
            commission.revenue_source,
            RevenueSource.PLATFORM_FEE,
        )

        self.assertEqual(
            commission.gross_revenue_amount,
            Decimal("5000.00"),
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
            f"invoice:{invoice.id}:platform_fee",
        )

    def test_paid_invoice_commission_is_duplicate_safe(self):
        invoice = Invoice.objects.create(
            ticket=self.ticket,
            title="Invoice Test",
            subtotal=Decimal("5000.00"),
            tax=Decimal("0.00"),
            total=Decimal("5000.00"),
            payment_method=Invoice.PaymentMethod.CARD,
        )

        invoice.mark_paid(method=Invoice.PaymentMethod.CARD)
        invoice.save()

        first = record_invoice_platform_fee_commission(invoice)
        second = record_invoice_platform_fee_commission(invoice)

        self.assertEqual(first.id, second.id)

        self.assertEqual(
            AffiliateCommissionLedger.objects.count(),
            1,
        )

    def test_uncollected_platform_fee_does_not_create_commission(self):
        invoice = Invoice.objects.create(
            ticket=self.ticket,
            title="Cash Invoice Test",
            subtotal=Decimal("5000.00"),
            tax=Decimal("0.00"),
            total=Decimal("5000.00"),
            payment_method=Invoice.PaymentMethod.CASH,
        )

        invoice.recompute_platform_fee()
        invoice.save()

        commission = record_invoice_platform_fee_commission(invoice)

        self.assertIsNone(commission)

        self.assertEqual(
            AffiliateCommissionLedger.objects.count(),
            0,
        )