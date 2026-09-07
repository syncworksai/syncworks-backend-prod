from django.contrib.auth import get_user_model
from django.test import TestCase

from personal_calendar.models import PersonalCalendarEvent
from customer_health.calendar_sync import sync_health_plan_to_calendar
from customer_health.models import CustomerHealthProfile


class HealthCalendarSyncTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="health-calendar", email="health-calendar@example.com", password="test-password")
        self.profile = CustomerHealthProfile.objects.create(user=self.user, profile_json={"timezone": "America/Chicago"})

    def test_planned_workout_creates_and_updates_calendar_event(self):
        self.profile.snapshot_json = {"week_plan": [{"id": "session-1", "ymd": "2026-09-08", "time": "07:30", "workout_name": "Upper Body", "duration_minutes": 60, "status": "Planned", "exercises": [{"name": "Bench"}]}]}
        sync_health_plan_to_calendar(self.profile)
        event = PersonalCalendarEvent.objects.get(owner=self.user, source="HEALTH")
        self.assertEqual(event.title, "Upper Body")
        self.assertEqual(event.start_at.astimezone().minute, 30)
        self.assertEqual(event.metadata["exercise_count"], 1)

        self.profile.snapshot_json["week_plan"][0]["workout_name"] = "Upper Body Updated"
        sync_health_plan_to_calendar(self.profile)
        self.assertEqual(PersonalCalendarEvent.objects.filter(owner=self.user, source="HEALTH").count(), 1)
        event.refresh_from_db()
        self.assertEqual(event.title, "Upper Body Updated")

    def test_removed_workout_is_archived(self):
        self.profile.snapshot_json = {"week_plan": [{"id": "session-2", "ymd": "2026-09-09", "workout_name": "Leg Day"}]}
        sync_health_plan_to_calendar(self.profile)
        self.profile.snapshot_json = {"week_plan": []}
        sync_health_plan_to_calendar(self.profile)
        self.assertEqual(PersonalCalendarEvent.objects.get(owner=self.user, source="HEALTH").status, "ARCHIVED")
