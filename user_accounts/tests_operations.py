from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from user_accounts.models import (
    Business,
    BusinessMember,
    CommunicationPreference,
    OperationalAlert,
    OperationalEvent,
    ServiceCategory,
    Ticket,
)
from user_accounts.viewsets.operations import (
    EventAlertCreateAPIView,
    OperationalAlertDetailAPIView,
    OperationalAlertListAPIView,
    TicketETAAPIView,
    TicketEventListCreateAPIView,
)


class OperationalEventTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.customer = User.objects.create_user(
            username="ops-customer",
            email="ops-customer@example.com",
            password="test-pass-123",
        )
        self.owner = User.objects.create_user(
            username="ops-owner",
            email="ops-owner@example.com",
            password="test-pass-123",
        )
        self.employee = User.objects.create_user(
            username="ops-employee",
            email="ops-employee@example.com",
            password="test-pass-123",
        )
        self.business = Business.objects.create(
            owner=self.owner,
            name="Operational Events Co",
        )
        BusinessMember.objects.create(
            business=self.business,
            user=self.employee,
            role="MANAGER",
            is_active=True,
        )
        self.category = ServiceCategory.objects.create(
            key="operations-service",
            name="Operations Service",
        )
        self.ticket = Ticket.objects.create(
            customer=self.customer,
            assigned_business=self.business,
            assigned_member=self.employee,
            category=self.category,
            status="EN_ROUTE",
        )
        self.factory = APIRequestFactory()

    def _auth(self, request, user=None):
        force_authenticate(request, user=user or self.employee)
        return request

    def test_eta_update_creates_customer_event_and_alert(self):
        request = self.factory.put(
            f"/api/v1/tickets/{self.ticket.id}/eta/",
            {
                "window_start": (timezone.now() + timedelta(hours=1)).isoformat(),
                "window_end": (timezone.now() + timedelta(hours=2)).isoformat(),
                "estimated_arrival": (timezone.now() + timedelta(minutes=75)).isoformat(),
                "status": "DELAYED",
                "delay_reason": "Traffic delay",
                "customer_message": "Your technician is running about 20 minutes late.",
            },
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = TicketETAAPIView.as_view()(
            self._auth(request),
            ticket_id=self.ticket.id,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "DELAYED")
        self.assertEqual(self.ticket.operational_events.count(), 1)
        self.assertEqual(
            OperationalAlert.objects.filter(recipient=self.customer).count(),
            1,
        )

    def test_invalid_eta_window_is_rejected(self):
        request = self.factory.put(
            f"/api/v1/tickets/{self.ticket.id}/eta/",
            {
                "window_start": (timezone.now() + timedelta(hours=2)).isoformat(),
                "window_end": (timezone.now() + timedelta(hours=1)).isoformat(),
                "status": "ON_TIME",
            },
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = TicketETAAPIView.as_view()(
            self._auth(request),
            ticket_id=self.ticket.id,
        )
        self.assertEqual(response.status_code, 400)

    def test_duplicate_alert_is_not_created_twice(self):
        event = OperationalEvent.objects.create(
            business=self.business,
            ticket=self.ticket,
            event_type="JOB_READY",
            visibility="BOTH",
            title="Job ready to resume",
        )
        payload = {
            "audience": "CUSTOMER",
            "channel": "IN_APP",
            "dedupe_suffix": "ready-v1",
        }
        first = self.factory.post(
            f"/api/v1/operations/events/{event.id}/alerts/",
            payload,
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        second = self.factory.post(
            f"/api/v1/operations/events/{event.id}/alerts/",
            payload,
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        first_response = EventAlertCreateAPIView.as_view()(
            self._auth(first),
            event_id=event.id,
        )
        second_response = EventAlertCreateAPIView.as_view()(
            self._auth(second),
            event_id=event.id,
        )
        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(OperationalAlert.objects.count(), 1)

    def test_disabled_email_channel_is_suppressed(self):
        CommunicationPreference.objects.create(
            user=self.customer,
            business=self.business,
            scope="BUSINESS",
            internal_inbox_enabled=True,
            email_notifications_enabled=False,
        )
        event = OperationalEvent.objects.create(
            business=self.business,
            ticket=self.ticket,
            event_type="STATUS_CHANGED",
            visibility="BOTH",
            title="Status updated",
        )
        request = self.factory.post(
            f"/api/v1/operations/events/{event.id}/alerts/",
            {"audience": "CUSTOMER", "channel": "EMAIL"},
            format="json",
            HTTP_X_BUSINESS_ID=str(self.business.id),
        )
        response = EventAlertCreateAPIView.as_view()(
            self._auth(request),
            event_id=event.id,
        )
        self.assertEqual(
            response.data["alert"]["status"],
            "SUPPRESSED",
        )

    def test_recipient_can_read_and_acknowledge_alert(self):
        event = OperationalEvent.objects.create(
            business=self.business,
            ticket=self.ticket,
            event_type="MESSAGE",
            visibility="CUSTOMER",
            title="Update available",
        )
        alert = OperationalAlert.objects.create(
            event=event,
            recipient=self.customer,
            audience="CUSTOMER",
            channel="IN_APP",
            dedupe_key="manual-alert-1",
        )
        request = self.factory.patch(
            f"/api/v1/operations/alerts/{alert.id}/",
            {"action": "acknowledge"},
            format="json",
        )
        response = OperationalAlertDetailAPIView.as_view()(
            self._auth(request, self.customer),
            alert_id=alert.id,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "ACKNOWLEDGED")
        self.assertIsNotNone(response.data["read_at"])
        self.assertIsNotNone(response.data["acknowledged_at"])
