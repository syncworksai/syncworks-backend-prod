from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from personal_calendar.models import PersonalCalendarEvent
from sync_ai.context import resolve_workspace


class SyncCalendarContextTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="sync-calendar",
            email="sync-calendar@example.com",
            password="test-password-123",
        )

    def test_calendar_context_exposes_next_event_conflicts_and_buffer(self):
        now = timezone.now()
        first = PersonalCalendarEvent.objects.create(
            owner=self.user,
            title="Softball Tournament",
            start_at=now + timedelta(hours=2),
            end_at=now + timedelta(hours=4),
            location_name="Sports Complex",
            city="Cullman",
            state="AL",
            arrival_buffer_minutes=45,
        )
        PersonalCalendarEvent.objects.create(
            owner=self.user,
            title="Team Meeting",
            start_at=now + timedelta(hours=3),
            end_at=now + timedelta(hours=3, minutes=30),
        )

        context = resolve_workspace(user=self.user, workspace="personal", business_id=None)
        calendar = context.data["calendar"]

        self.assertTrue(calendar["available"])
        self.assertEqual(calendar["next_event"]["id"], first.id)
        self.assertEqual(calendar["next_event"]["title"], "Softball Tournament")
        self.assertEqual(calendar["next_event"]["arrival_buffer_minutes"], 45)
        self.assertEqual(len(calendar["conflicts"]), 1)
        self.assertFalse(calendar["travel_time"]["available"])

    def test_calendar_context_is_user_scoped_and_omits_description_metadata(self):
        other = get_user_model().objects.create_user(
            username="calendar-other",
            email="calendar-other@example.com",
            password="test-password-123",
        )
        PersonalCalendarEvent.objects.create(
            owner=other,
            title="Other User Private Event",
            description="private description",
            metadata={"secret": "private metadata"},
            start_at=timezone.now() + timedelta(hours=1),
        )
        own = PersonalCalendarEvent.objects.create(
            owner=self.user,
            title="My Appointment",
            description="medical detail that should not be in SYNC summary",
            metadata={"secret": "do not expose"},
            start_at=timezone.now() + timedelta(hours=2),
        )

        context = resolve_workspace(user=self.user, workspace="personal", business_id=None)
        calendar = context.data["calendar"]
        text = str(calendar)

        self.assertEqual(calendar["next_event"]["id"], own.id)
        self.assertNotIn("Other User Private Event", text)
        self.assertNotIn("private description", text)
        self.assertNotIn("medical detail", text)
        self.assertNotIn("do not expose", text)
