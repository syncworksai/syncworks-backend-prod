from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from sync_ai.calendar_context import build_sync_calendar_context

from .models import PersonalCalendarEvent
from .travel_monitor import enable_trip_monitoring, refresh_due_trip_monitors, refresh_monitored_trip


class TravelMonitorTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="travel-monitor-user",
            email="travel-monitor@example.com",
            password="test-password-123",
        )
        self.event = PersonalCalendarEvent.objects.create(
            owner=self.user,
            title="Tournament",
            start_at=timezone.now() + timedelta(hours=2),
            location_name="Sports Complex",
            address_line1="100 Field Way",
            city="Montgomery",
            state="AL",
            arrival_buffer_minutes=30,
        )

    def ready_plan(self, *, delay=300, leave_shift_minutes=0, weather_risk="LOW"):
        leave_by = self.event.start_at - timedelta(minutes=90 + leave_shift_minutes)
        return {
            "event_id": self.event.id,
            "event_title": self.event.title,
            "event_start_at": self.event.start_at.isoformat(),
            "destination": {"label": "Sports Complex", "coordinates_available": True},
            "arrival_buffer_minutes": 30,
            "route": {
                "status": "READY",
                "provider": "GOOGLE_ROUTES",
                "traffic_aware": True,
                "duration_seconds": 3600 + delay,
                "static_duration_seconds": 3600,
                "traffic_delay_seconds": delay,
                "leave_by": leave_by.isoformat(),
            },
            "weather": {
                "status": "READY",
                "provider": "NWS",
                "risk": weather_risk,
                "short_forecast": "Partly Cloudy" if weather_risk == "LOW" else "Thunderstorms",
                "precipitation_probability": 20 if weather_risk == "LOW" else 80,
                "temperature": 82,
                "temperature_unit": "F",
            },
            "recommendations": [],
            "generated_at": timezone.now().isoformat(),
        }

    def test_enabling_monitoring_is_explicit_and_stores_origin(self):
        monitor = enable_trip_monitoring(self.event, 32.37, -86.30)
        self.event.refresh_from_db()
        self.assertTrue(monitor["enabled"])
        self.assertEqual(self.event.metadata["travel_monitor"]["origin"]["latitude"], 32.37)
        self.assertEqual(self.event.metadata["travel_monitor"]["origin"]["longitude"], -86.30)

    @patch("personal_calendar.travel_monitor.build_travel_plan")
    def test_refresh_detects_meaningful_traffic_and_weather_change(self, build_plan):
        enable_trip_monitoring(self.event, 32.37, -86.30)
        metadata = dict(self.event.metadata or {})
        metadata["travel_assist"] = self.ready_plan(delay=0, leave_shift_minutes=0, weather_risk="LOW")
        self.event.metadata = metadata
        self.event.save(update_fields=("metadata", "updated_at"))
        build_plan.return_value = self.ready_plan(delay=1200, leave_shift_minutes=20, weather_risk="HIGH")

        result = refresh_monitored_trip(self.event)
        self.event.refresh_from_db()

        self.assertEqual(result["status"], "UPDATED")
        self.assertIsNotNone(result["alert"])
        self.assertEqual(result["alert"]["severity"], "HIGH")
        messages = " ".join(result["alert"]["messages"])
        self.assertIn("Traffic added", messages)
        self.assertIn("Leave 20 minutes earlier", messages)
        self.assertIn("Weather risk increased", messages)
        self.assertEqual(self.event.metadata["travel_monitor"]["last_alert"]["severity"], "HIGH")

    @patch("personal_calendar.travel_monitor.build_travel_plan")
    def test_runtime_checks_opted_in_upcoming_events(self, build_plan):
        enable_trip_monitoring(self.event, 32.37, -86.30)
        build_plan.return_value = self.ready_plan()
        result = refresh_due_trip_monitors(now=timezone.now())
        self.assertEqual(result["checked"], 1)
        build_plan.assert_called_once()

    @patch("personal_calendar.travel_monitor.build_travel_plan")
    def test_runtime_skips_events_without_opt_in(self, build_plan):
        result = refresh_due_trip_monitors(now=timezone.now())
        self.assertEqual(result["checked"], 0)
        self.assertGreaterEqual(result["skipped"], 1)
        build_plan.assert_not_called()

    @patch("personal_calendar.travel_monitor.build_travel_plan")
    def test_sync_calendar_context_exposes_leave_by_and_alert_not_saved_origin(self, build_plan):
        enable_trip_monitoring(self.event, 32.37, -86.30)
        metadata = dict(self.event.metadata or {})
        metadata["travel_assist"] = self.ready_plan(delay=1200, weather_risk="HIGH")
        metadata["travel_monitor"]["last_alert"] = {
            "severity": "HIGH",
            "messages": ["Traffic changed."],
            "created_at": timezone.now().isoformat(),
        }
        self.event.metadata = metadata
        self.event.save(update_fields=("metadata", "updated_at"))

        context = build_sync_calendar_context(self.user)
        travel = context["next_event"]["travel"]
        self.assertTrue(travel["monitoring_enabled"])
        self.assertIsNotNone(travel["leave_by"])
        self.assertEqual(travel["weather"]["risk"], "HIGH")
        self.assertNotIn("origin", travel)
        self.assertTrue(any(item["code"] == "TRAVEL_CHANGE" for item in context["attention"]))
