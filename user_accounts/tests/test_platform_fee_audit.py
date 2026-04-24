from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from user_accounts.models import Business, Invoice, Ticket, User
from user_accounts.services.cash_fee_billing import generate_monthly_cash_fee_invoices


class TestPlatformFeeInvoiceBehavior(TestCase):
    def test_platform_fee_rate_default_and_rounding(self):
        inv = Invoice.objects.create(total="10.05")
        self.assertEqual(inv.platform_fee_rate_bps, 100)
        self.assertEqual(str(inv.platform_fee_amount), "0.10")

    def test_card_payment_marks_platform_fee_collected(self):
        inv = Invoice.objects.create(total="100.00", payment_method=Invoice.PaymentMethod.CARD)
        inv.mark_paid(method=Invoice.PaymentMethod.CARD)
        inv.save()

        self.assertEqual(inv.status, Invoice.Status.PAID)
        self.assertEqual(str(inv.platform_fee_amount), "1.00")
        self.assertTrue(inv.platform_fee_collected)
        self.assertIsNotNone(inv.platform_fee_collected_at)

    def test_cash_and_other_payment_do_not_collect_fee_immediately(self):
        inv_cash = Invoice.objects.create(total="100.00", payment_method=Invoice.PaymentMethod.CASH)
        inv_cash.mark_paid(method=Invoice.PaymentMethod.CASH)
        inv_cash.save()

        inv_other = Invoice.objects.create(total="100.00", payment_method=Invoice.PaymentMethod.OTHER)
        inv_other.mark_paid(method=Invoice.PaymentMethod.OTHER)
        inv_other.save()

        self.assertFalse(inv_cash.platform_fee_collected)
        self.assertFalse(inv_other.platform_fee_collected)
        self.assertEqual(str(inv_cash.platform_fee_amount), "1.00")
        self.assertEqual(str(inv_other.platform_fee_amount), "1.00")


@override_settings(STRIPE_SECRET_KEY="sk_test_123", STRIPE_WEBHOOK_SECRET="whsec_test")
class TestPlatformFeeWebhookAndCashFeeFlow(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("user_accounts.viewsets.invoice_checkout.stripe.Webhook.construct_event")
    def test_duplicate_checkout_completed_webhook_is_safe_for_fee_tracking(self, mock_construct_event):
        inv = Invoice.objects.create(
            total="120.00",
            status=Invoice.Status.SENT,
            payment_method=Invoice.PaymentMethod.CARD,
            stripe_checkout_session_id="cs_test_123",
        )

        mock_construct_event.return_value = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "payment_status": "paid",
                    "payment_intent": "pi_test_123",
                    "metadata": {"invoice_id": str(inv.id)},
                }
            },
        }

        path = "/api/v1/billing/invoices/webhook/"
        r1 = self.client.post(path, data=b"{}", content_type="application/json", HTTP_STRIPE_SIGNATURE="sig")
        r2 = self.client.post(path, data=b"{}", content_type="application/json", HTTP_STRIPE_SIGNATURE="sig")

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)

        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.PAID)
        self.assertEqual(str(inv.platform_fee_amount), "1.20")
        self.assertTrue(inv.platform_fee_collected)
        self.assertEqual(inv.stripe_payment_intent_id, "pi_test_123")

    def test_cash_fee_summary_captures_cash_payment_and_rounds_half_up(self):
        owner = User.objects.create_user(username="owner-fee@test.com", email="owner-fee@test.com", password="Password123!")
        customer = User.objects.create_user(
            username="customer-fee@test.com",
            email="customer-fee@test.com",
            password="Password123!",
        )
        biz = Business.objects.create(name="Fee Biz", owner=owner)

        today = timezone.localdate()
        Ticket.objects.create(
            customer=customer,
            assigned_business=biz,
            payment_method=Ticket.PaymentMethod.CASH,
            total_amount_cents=50,  # $0.50 => 1% = $0.005 => rounds half-up to $0.01 (1 cent)
            cash_confirmed_at=timezone.now(),
            status=Ticket.Status.PAID,
        )

        res = generate_monthly_cash_fee_invoices(
            period_start=today,
            period_end=today,
            fee_bps=100,
            due_days=7,
        )
        self.assertEqual(res.invoices_created, 1)
        inv = biz.cash_fee_invoices.get(period_start=today, period_end=today)
        self.assertEqual(inv.amount_cents, 1)
