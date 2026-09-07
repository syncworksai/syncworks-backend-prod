from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from personal_calendar.models import PersonalCalendarEvent
from user_accounts.models import Ticket, TicketOperationalProfile


class TicketPersonalCalendarSyncTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="calendar-ticket", email="calendar-ticket@example.com", password="test")

    def test_scheduled_ticket_creates_and_business_change_updates_one_event(self):
        first = timezone.now() + timedelta(days=2)
        ticket = Ticket.objects.create(customer=self.user, work_title="HVAC service repair", service_address="123 Main St", service_zip="36104", status="SCHEDULED", scheduled_at=first)
        event = PersonalCalendarEvent.objects.get(owner=self.user, source="TICKET", external_event_id=str(ticket.pk))
        self.assertEqual(event.start_at, first)
        self.assertEqual(event.metadata["deep_link"], f"/tickets/{ticket.pk}")

        moved = first + timedelta(hours=3)
        operations = TicketOperationalProfile.objects.create(ticket=ticket, scheduled_start=moved, scheduled_end=moved + timedelta(minutes=90))
        event.refresh_from_db()
        self.assertEqual(event.start_at, moved)
        self.assertEqual(event.end_at, moved + timedelta(minutes=90))
        self.assertEqual(PersonalCalendarEvent.objects.filter(owner=self.user, source="TICKET").count(), 1)

        operations.scheduled_start = moved + timedelta(days=1)
        operations.scheduled_end = moved + timedelta(days=1, minutes=90)
        operations.save()
        event.refresh_from_db()
        self.assertEqual(event.start_at, moved + timedelta(days=1))

    def test_cancelled_ticket_cancels_calendar_event(self):
        ticket = Ticket.objects.create(customer=self.user, work_title="Plumbing visit", status="SCHEDULED", scheduled_at=timezone.now() + timedelta(days=1))
        ticket.status = "CANCELLED"
        ticket.save(update_fields=["status"])
        event = PersonalCalendarEvent.objects.get(owner=self.user, source="TICKET", external_event_id=str(ticket.pk))
        self.assertEqual(event.status, PersonalCalendarEvent.Status.CANCELLED)
