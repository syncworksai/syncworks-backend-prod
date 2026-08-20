from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from user_accounts.models import Business, BusinessMember, Invoice, InvoiceEvent, ServiceRequest, Ticket


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    }
)
class InvoiceExperienceTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="invoice-owner", email="owner-invoice@example.com", password="test-password-123")
        self.customer = User.objects.create_user(username="invoice-customer", email="customer-invoice@example.com", password="test-password-123")
        self.other_owner = User.objects.create_user(username="other-owner", email="other-owner@example.com", password="test-password-123")
        self.accounting = User.objects.create_user(username="accounting", email="accounting@example.com", password="test-password-123")
        self.business = Business.objects.create(owner=self.owner, name="Invoice Test Co", base_zip="36104")
        self.other_business = Business.objects.create(owner=self.other_owner, name="Other Co", base_zip="35203")
        BusinessMember.objects.create(business=self.business, user=self.owner, role="OWNER", is_active=True, can_view_financials=True, can_manage_invoices=True)
        BusinessMember.objects.create(business=self.business, user=self.accounting, role="ACCOUNTING", is_active=True, can_view_financials=True, can_manage_invoices=True)
        self.owner_token = Token.objects.create(user=self.owner)
        self.accounting_token = Token.objects.create(user=self.accounting)

    def make_ticket(self, business=None, total_cents=12500, marketplace=True):
        business = business or self.business
        req = ServiceRequest.objects.create(customer=self.customer, title="Completed repair", description="Finished work", address="100 Main St", zip_code="36104", status="MATCHED", target_business=business)
        return Ticket.objects.create(
            service_request=req,
            customer=self.customer,
            assigned_business=business,
            service_address="100 Main St",
            service_zip="36104",
            status=Ticket.Status.COMPLETED,
            total_amount_cents=total_cents,
            is_marketplace=marketplace,
        )

    def auth_owner(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.owner_token.key}", HTTP_X_BUSINESS_ID=str(self.business.id))

    def test_completed_job_appears_ready_to_bill_and_can_create_draft(self):
        ticket = self.make_ticket()
        self.auth_owner()
        center = self.client.get("/api/v1/sync-ai/business/invoices/")
        self.assertEqual(center.status_code, 200)
        self.assertEqual(center.data["summary"]["ready_to_bill_count"], 1)
        created = self.client.post(f"/api/v1/sync-ai/business/invoices/from-ticket/{ticket.id}/", {}, format="json")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["derived_state"], "DRAFT")
        self.assertEqual(created.data["total"], "125.00")
        self.assertTrue(created.data["marketplace_origin"])
        self.assertEqual(InvoiceEvent.objects.filter(invoice_id=created.data["id"], event_type="CREATED").count(), 1)

    def test_external_full_payment_does_not_claim_platform_fee_collected(self):
        ticket = self.make_ticket(total_cents=20000)
        invoice = Invoice.objects.create(ticket=ticket, title="Repair", subtotal=Decimal("200.00"), total=Decimal("200.00"), status=Invoice.Status.SENT)
        self.auth_owner()
        response = self.client.post(
            f"/api/v1/sync-ai/business/invoices/{invoice.id}/record-payment/",
            {"amount": "200.00", "source": "EXTERNAL_POS", "reference": "POS-123"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["derived_state"], "PAID")
        self.assertFalse(response.data["platform_fee_collected"])
        event = InvoiceEvent.objects.get(invoice=invoice, event_type=InvoiceEvent.EventType.PAID)
        self.assertEqual(event.payment_source, "EXTERNAL_POS")
        self.assertIn("did not process", event.message)

    def test_partial_payment_keeps_balance_and_sent_state(self):
        ticket = self.make_ticket(total_cents=10000)
        invoice = Invoice.objects.create(ticket=ticket, title="Repair", subtotal=Decimal("100.00"), total=Decimal("100.00"), status=Invoice.Status.SENT)
        self.auth_owner()
        response = self.client.post(
            f"/api/v1/sync-ai/business/invoices/{invoice.id}/record-payment/",
            {"amount": "25.00", "source": "CHECK"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["derived_state"], "PARTIALLY_PAID")
        self.assertEqual(response.data["balance_due"], "75.00")

    def test_invoice_center_is_business_scoped(self):
        mine = self.make_ticket()
        other = self.make_ticket(business=self.other_business, marketplace=False)
        Invoice.objects.create(ticket=mine, title="Mine", subtotal=Decimal("10"), total=Decimal("10"))
        Invoice.objects.create(ticket=other, title="Other", subtotal=Decimal("99"), total=Decimal("99"))
        self.auth_owner()
        response = self.client.get("/api/v1/sync-ai/business/invoices/")
        self.assertEqual(response.status_code, 200)
        titles = {row["title"] for row in response.data["results"]}
        self.assertIn("Mine", titles)
        self.assertNotIn("Other", titles)

    def test_accounting_permission_can_manage_invoices(self):
        ticket = self.make_ticket()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.accounting_token.key}", HTTP_X_BUSINESS_ID=str(self.business.id))
        response = self.client.post(f"/api/v1/sync-ai/business/invoices/from-ticket/{ticket.id}/", {}, format="json")
        self.assertEqual(response.status_code, 201)
