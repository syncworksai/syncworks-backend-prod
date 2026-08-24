from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from user_accounts.models import Business, Invoice, Notification, ServiceRequest, Ticket


@override_settings(
    STRIPE_SECRET_KEY="sk_test_build19",
    PLATFORM_BASE_URL="https://syncworksapp.com",
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    },
)
class CustomerInvoicePaymentLoopTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(username="invoice-customer", email="customer@example.com", password="test-password-123")
        self.owner = User.objects.create_user(username="invoice-owner", email="owner@example.com", password="test-password-123")
        self.customer_token = Token.objects.create(user=self.customer)
        self.owner_token = Token.objects.create(user=self.owner)
        self.business = Business.objects.create(owner=self.owner, name="Build 19 Services", base_zip="36104", accepts_marketplace_tickets=True)
        req = ServiceRequest.objects.create(customer=self.customer, title="Completed repair", description="Repair", address="100 Main St", zip_code="36104", status="MATCHED", target_business=self.business)
        self.ticket = Ticket.objects.create(service_request=req, customer=self.customer, assigned_business=self.business, status=Ticket.Status.COMPLETED, total_amount_cents=12500)

    def auth_customer(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.customer_token.key}")

    def auth_owner(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.owner_token.key}", HTTP_X_BUSINESS_ID=str(self.business.id))

    def make_invoice(self, status=Invoice.Status.SENT, amount_paid="0.00"):
        return Invoice.objects.create(
            ticket=self.ticket,
            title="Completed repair",
            subtotal=Decimal("125.00"),
            total=Decimal("125.00"),
            amount_paid=Decimal(amount_paid),
            status=status,
        )

    def test_customer_center_hides_drafts_and_reports_balance(self):
        sent = self.make_invoice(amount_paid="25.00")
        Invoice.objects.create(ticket=self.ticket, title="Draft", total=Decimal("9.00"), status=Invoice.Status.DRAFT)
        self.auth_customer()
        response = self.client.get("/api/v1/sync-ai/customer/invoices/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], sent.id)
        self.assertEqual(response.data["results"][0]["balance_due"], "100.00")
        self.assertEqual(response.data["summary"]["outstanding"], "100.00")

    def test_business_send_creates_customer_billing_notification(self):
        invoice = self.make_invoice(status=Invoice.Status.DRAFT)
        self.auth_owner()
        response = self.client.post(f"/api/v1/sync-ai/business/invoices/{invoice.id}/send/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        invoice.refresh_from_db()
        self.ticket.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.SENT)
        self.assertEqual(self.ticket.status, Ticket.Status.INVOICED)
        note = Notification.objects.filter(recipient=self.customer, type=Notification.TYPE_BILLING).latest("created_at")
        self.assertEqual(note.data["invoice_id"], invoice.id)
        self.assertEqual(note.data["route"], f"/customer/invoices?invoice_id={invoice.id}")

    @patch("user_accounts.viewsets.invoice_checkout.stripe.checkout.Session.create")
    def test_checkout_charges_only_remaining_balance(self, session_create):
        invoice = self.make_invoice(amount_paid="25.00")
        session_create.return_value = SimpleNamespace(id="cs_test_build19", url="https://checkout.stripe.test/session")
        self.auth_customer()
        response = self.client.post(f"/api/v1/billing/invoices/{invoice.id}/checkout/", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["amount_due"], "100.00")
        kwargs = session_create.call_args.kwargs
        self.assertEqual(kwargs["line_items"][0]["price_data"]["unit_amount"], 10000)
        self.assertIn(f"invoice_id={invoice.id}", kwargs["success_url"])
        self.assertIn("/customer/invoices", kwargs["success_url"])
