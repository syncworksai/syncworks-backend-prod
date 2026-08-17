from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import PersonalCalendarEvent, PersonalCalendarEventAudit


User = get_user_model()


class PersonalCalendarApiTests(APITestCase):
    def make_user(self, email):
        user = User.objects.create_user(
            username=email.split("@", 1)[0],
            email=email,
            password="test-password-123",
        )
        token, _ = Token.objects.get_or_create(user=user)
        return user, token

    def authenticate(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def event_payload(self, **overrides):
        start = timezone.now() + timedelta(days=1)
        payload = {
            "title": "Softball tournament",
            "description": "First game",
            "start_at": start.isoformat(),
            "end_at": (start + timedelta(hours=2)).isoformat(),
            "timezone": "America/Chicago",
            "location_name": "Cullman Sports Complex",
            "address_line1": "1500 Sportsman Lake Rd",
            "city": "Cullman",
            "state": "AL",
            "postal_code": "35055",
            "arrival_buffer_minutes": 45,
            "reminder_minutes": 30,
        }
        payload.update(overrides)
        return payload

    def test_user_can_create_and_list_own_event(self):
        user, token = self.make_user("calendar-owner@example.com")
        self.authenticate(token)
        response = self.client.post("/api/v1/personal-calendar/events/", self.event_payload(), format="json")
        self.assertEqual(response.status_code, 201)
        event = PersonalCalendarEvent.objects.get(owner=user)
        self.assertEqual(event.audit_entries.count(), 1)
        self.assertEqual(event.audit_entries.first().action, PersonalCalendarEventAudit.Action.CREATED)
        response = self.client.get("/api/v1/personal-calendar/events/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_events_are_strictly_owner_scoped(self):
        first_user, _ = self.make_user("first@example.com")
        _, second_token = self.make_user("second@example.com")
        event = PersonalCalendarEvent.objects.create(
            owner=first_user,
            title="Private event",
            start_at=timezone.now() + timedelta(days=1),
        )
        self.authenticate(second_token)
        response = self.client.get("/api/v1/personal-calendar/events/")
        self.assertEqual(response.data["count"], 0)
        response = self.client.get(f"/api/v1/personal-calendar/events/{event.id}/")
        self.assertEqual(response.status_code, 404)

    def test_end_time_before_start_is_rejected(self):
        _, token = self.make_user("invalid-event@example.com")
        self.authenticate(token)
        start = timezone.now() + timedelta(days=2)
        response = self.client.post(
            "/api/v1/personal-calendar/events/",
            self.event_payload(
                start_at=start.isoformat(),
                end_at=(start - timedelta(hours=1)).isoformat(),
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("end_at", response.data)

    def test_archive_cancel_and_restore_are_audited(self):
        user, token = self.make_user("event-actions@example.com")
        event = PersonalCalendarEvent.objects.create(
            owner=user,
            title="Appointment",
            start_at=timezone.now() + timedelta(days=1),
        )
        self.authenticate(token)
        for action, expected in (
            ("cancel", PersonalCalendarEvent.Status.CANCELLED),
            ("restore", PersonalCalendarEvent.Status.ACTIVE),
            ("archive", PersonalCalendarEvent.Status.ARCHIVED),
        ):
            response = self.client.post(
                f"/api/v1/personal-calendar/events/{event.id}/{action}/",
                {},
                format="json",
            )
            self.assertEqual(response.status_code, 200)
            event.refresh_from_db()
            self.assertEqual(event.status, expected)
        self.assertEqual(event.audit_entries.count(), 3)

    def test_date_range_and_status_filters(self):
        user, token = self.make_user("filters@example.com")
        now = timezone.now()
        PersonalCalendarEvent.objects.create(owner=user, title="Soon", start_at=now + timedelta(days=1))
        PersonalCalendarEvent.objects.create(
            owner=user,
            title="Later",
            start_at=now + timedelta(days=30),
            status=PersonalCalendarEvent.Status.ARCHIVED,
        )
        self.authenticate(token)
        response = self.client.get(
            "/api/v1/personal-calendar/events/",
            {
                "start": now.isoformat(),
                "end": (now + timedelta(days=7)).isoformat(),
                "status": "ACTIVE",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["title"], "Soon")
