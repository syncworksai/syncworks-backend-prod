from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from sync_ai.billing_runtime import process_invoice_reminders
from user_accounts.models import (
    Business,
    Invoice,
    InvoiceAutomationSettings,
    InvoiceEvent,
    Notification,
    ServiceRequest,
    Ticket,
)


@override_settings(
    REST_FRAMEWORK={
        "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
        "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    }
)
class BillingRuntimeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="billing-runtime-owner", email="owner@example.com", password="x")
        self.customer = User.objects.create_user(username="billing-runtime-customer", email="customer@example.com", password="x")
        self.business = Business.objects.create(owner=self.owner, name="Runtime Co", base_zip="36104")
        self.request = ServiceRequest.objects.create(
            customer=self.customer,
            title="Completed work",
            description="done",
            address="100 Main St",
            zip_code="36104",
            status="MATCHED",
            target_business=self.business,
        )
        self.ticket = Ticket.objects.create(
            service_request=self.request,
            customer=self.customer,
            assigned_business=self.business,
            service_address="100 Main St",
            service_zip="36104",
            status=Ticket.Status.INVOICED,
            total_amount_cents=10000,
        )
        self.today = timezone.localdate()
        self.invoice = Invoice.objects.create(
            ticket=self.ticket,
            title="Work",
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            status=Invoice.Status.SENT,
            due_date=self.today,
        )
        self.settings = InvoiceAutomationSettings.objects.create(
            business=self.business,
            auto_reminders_enabled=True,
            reminder_before_due_days=3,
            reminder_on_due_date=True,
            reminder_after_due_days=[3, 7, 14],
        )

    @patch("sync_ai.billing_runtime.send_mail", return_value=1)
    def test_due_date_reminder_is_sent_once(self, _send_mail):
        first = process_invoice_reminders(today=self.today)
        second = process_invoice_reminders(today=self.today)
        self.assertEqual(first["sent"], 1)
        self.assertEqual(second["sent"], 0)
        self.assertEqual(second["deduped"], 1)
        self.assertEqual(Notification.objects.filter(recipient=self.customer, type=Notification.TYPE_BILLING).count(), 1)
        event = InvoiceEvent.objects.get(invoice=self.invoice, event_type=InvoiceEvent.EventType.REMINDER)
        self.assertIn("AUTO_REMINDER_V1", event.external_reference)
        self.assertEqual(event.metadata["rule"], "DUE_DATE")

    @patch("sync_ai.billing_runtime.send_mail", return_value=1)
    def test_after_due_cadence_runs_only_on_configured_day(self, _send_mail):
        self.invoice.due_date = self.today - timedelta(days=7)
        self.invoice.save(update_fields=["due_date"])
        result = process_invoice_reminders(today=self.today)
        self.assertEqual(result["sent"], 1)
        event = InvoiceEvent.objects.get(invoice=self.invoice, event_type=InvoiceEvent.EventType.REMINDER)
        self.assertEqual(event.metadata["rule"], "AFTER_7")

    @patch("sync_ai.billing_runtime.send_mail", return_value=1)
    def test_disabled_business_does_not_send(self, _send_mail):
        self.settings.auto_reminders_enabled = False
        self.settings.save(update_fields=["auto_reminders_enabled"])
        result = process_invoice_reminders(today=self.today)
        self.assertEqual(result["sent"], 0)
        self.assertEqual(Notification.objects.count(), 0)

    def test_receivables_endpoint_exposes_forecast_and_runtime_state(self):
        token = Token.objects.create(user=self.owner)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}", HTTP_X_BUSINESS_ID=str(self.business.id))
        response = client.get("/api/v1/sync-ai/business/receivables/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["outstanding_total"], "100.00")
        self.assertEqual(response.data["collection_forecast"]["due_next_7_days"], "100.00")
        self.assertEqual(response.data["automation"]["runtime"], "ACTIVE_DAILY")
