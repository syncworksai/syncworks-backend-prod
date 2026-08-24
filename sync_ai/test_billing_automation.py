from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from user_accounts.models import Business, BusinessMember, Invoice, InvoiceAutomationSettings, Notification, ServiceRequest, Ticket


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    }
)
class BillingAutomationTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="billing-auto-owner", email="billing-auto-owner@example.com", password="test-password-123")
        self.customer = User.objects.create_user(username="billing-auto-customer", email="billing-auto-customer@example.com", password="test-password-123")
        self.business = Business.objects.create(owner=self.owner, name="Automation Test Co", base_zip="36104")
        BusinessMember.objects.create(business=self.business, user=self.owner, role="OWNER", is_active=True, can_manage_settings=True, can_view_financials=True, can_manage_invoices=True)
        self.token = Token.objects.create(user=self.owner)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}", HTTP_X_BUSINESS_ID=str(self.business.id))

    def make_ticket(self, cents=12500):
        req = ServiceRequest.objects.create(customer=self.customer, title="Completed service", description="Finished", address="100 Main St", zip_code="36104", status="MATCHED", target_business=self.business)
        return Ticket.objects.create(service_request=req, customer=self.customer, assigned_business=self.business, service_address="100 Main St", service_zip="36104", status=Ticket.Status.COMPLETED, total_amount_cents=cents, is_marketplace=True)

    def test_defaults_are_draft_first_and_net_15(self):
        response = self.client.get("/api/v1/sync-ai/business/billing-automation/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["auto_send_invoices"])
        self.assertEqual(response.data["due_terms"], "NET_15")
        self.assertEqual(response.data["due_days"], 15)

        ticket = self.make_ticket()
        created = self.client.post(f"/api/v1/sync-ai/business/invoices/from-ticket/{ticket.id}/", {}, format="json")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["derived_state"], "DRAFT")
        self.assertEqual(created.data["due_date"], (timezone.localdate() + timedelta(days=15)).isoformat())
        self.assertEqual(Notification.objects.filter(recipient=self.customer, type=Notification.TYPE_BILLING).count(), 0)

    def test_auto_send_is_opt_in_and_notifies_customer(self):
        saved = self.client.patch("/api/v1/sync-ai/business/billing-automation/", {"auto_send_invoices": True, "due_terms": "NET_30"}, format="json")
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.data["auto_send_invoices"])
        self.assertEqual(saved.data["due_days"], 30)

        ticket = self.make_ticket()
        created = self.client.post(f"/api/v1/sync-ai/business/invoices/from-ticket/{ticket.id}/", {}, format="json")
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["derived_state"], "SENT")
        self.assertEqual(created.data["due_date"], (timezone.localdate() + timedelta(days=30)).isoformat())
        note = Notification.objects.get(recipient=self.customer, type=Notification.TYPE_BILLING)
        self.assertEqual(note.data["event"], "INVOICE_SENT")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, Ticket.Status.INVOICED)

    def test_ar_aging_and_review_recommendation(self):
        settings = InvoiceAutomationSettings.objects.create(
            business=self.business,
            pause_new_non_emergency_work_when_overdue=True,
            overdue_pause_threshold_days=30,
            overdue_pause_threshold_cents=5000,
        )
        ticket = self.make_ticket(cents=20000)
        Invoice.objects.create(ticket=ticket, title="Past due", subtotal=Decimal("200.00"), total=Decimal("200.00"), amount_paid=Decimal("25.00"), status=Invoice.Status.SENT, due_date=timezone.localdate() - timedelta(days=45))

        response = self.client.get("/api/v1/sync-ai/business/receivables/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["aging"]["31_60"], "175.00")
        self.assertEqual(response.data["overdue_total"], "175.00")
        self.assertEqual(response.data["overdue_customer_count"], 1)
        self.assertTrue(response.data["customers"][0]["pause_recommended"])
        self.assertEqual(response.data["customers"][0]["oldest_days"], 45)
        settings.refresh_from_db()
        self.assertTrue(settings.pause_new_non_emergency_work_when_overdue)

    def test_reminder_cadence_is_validated_and_saved(self):
        response = self.client.patch(
            "/api/v1/sync-ai/business/billing-automation/",
            {"auto_reminders_enabled": True, "reminder_before_due_days": 2, "reminder_on_due_date": True, "reminder_after_due_days": [3, 7, 14, 30]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["auto_reminders_enabled"])
        self.assertEqual(response.data["reminder_after_due_days"], [3, 7, 14, 30])
