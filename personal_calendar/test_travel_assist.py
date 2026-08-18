from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import PersonalCalendarEvent, PersonalCalendarEventAudit
from .travel_assist import build_travel_plan

User = get_user_model()


class TravelAssistApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="travel-user",
            email="travel@example.com",
            password="pass12345",
        )
        self.other = User.objects.create_user(
            username="other-travel-user",
            email="other-travel@example.com",
            password="pass12345",
        )
        self.event = PersonalCalendarEvent.objects.create(
            owner=self.user,
            title="Tournament",
            start_at=timezone.now() + timedelta(days=2),
            location_name="Sportsplex",
            address_line1="100 Ballpark Way",
            city="Birmingham",
            state="AL",
            postal_code="35203",
            country="US",
            arrival_buffer_minutes=30,
            status=PersonalCalendarEvent.Status.ACTIVE,
        )
        self.client.force_authenticate(user=self.user)

    def test_travel_plan_requires_valid_device_coordinates(self):
        response = self.client.post(
            f"/api/v1/personal-calendar/events/{self.event.id}/travel-plan/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("personal_calendar.views.build_travel_plan")
    def test_travel_plan_is_cached_in_event_metadata_without_device_coordinates(self, build_plan):
        build_plan.return_value = {
            "event_id": self.event.id,
            "route": {
                "status": "READY",
                "provider": "GOOGLE_ROUTES",
                "traffic_aware": True,
                "leave_by": (self.event.start_at - timedelta(hours=2)).isoformat(),
            },
            "weather": {"status": "READY", "provider": "NWS", "risk": "LOW"},
            "recommendations": ["Leave on time."],
            "generated_at": timezone.now().isoformat(),
        }
        response = self.client.post(
            f"/api/v1/personal-calendar/events/{self.event.id}/travel-plan/",
            {"latitude": 32.3668, "longitude": -86.3000},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.event.refresh_from_db()
        cached = self.event.metadata.get("travel_assist")
        self.assertEqual(cached["route"]["provider"], "GOOGLE_ROUTES")
        self.assertNotIn("latitude", cached)
        self.assertNotIn("longitude", cached)
        self.assertTrue(
            PersonalCalendarEventAudit.objects.filter(
                event=self.event,
                changes__fields=["metadata.travel_assist"],
            ).exists()
        )

    def test_user_cannot_generate_plan_for_another_users_event(self):
        private_event = PersonalCalendarEvent.objects.create(
            owner=self.other,
            title="Private event",
            start_at=timezone.now() + timedelta(days=1),
        )
        response = self.client.post(
            f"/api/v1/personal-calendar/events/{private_event.id}/travel-plan/",
            {"latitude": 32.3668, "longitude": -86.3000},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TravelAssistServiceTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="travel-service-user",
            email="travel-service@example.com",
            password="pass12345",
        )
        self.event = PersonalCalendarEvent.objects.create(
            owner=self.user,
            title="Away game",
            start_at=timezone.now() + timedelta(days=2),
            location_name="Test Park",
            address_line1="200 Stadium Dr",
            city="Birmingham",
            state="AL",
            country="US",
            arrival_buffer_minutes=45,
        )

    @patch.dict("os.environ", {"GOOGLE_MAPS_SERVER_API_KEY": "test-key"}, clear=False)
    @patch("personal_calendar.travel_assist.requests.get")
    @patch("personal_calendar.travel_assist.requests.post")
    def test_plan_separates_live_traffic_delay_from_weather_risk(self, post, get):
        geocode = type("Response", (), {})()
        geocode.raise_for_status = lambda: None
        geocode.json = lambda: {
            "status": "OK",
            "results": [{"geometry": {"location": {"lat": 33.5186, "lng": -86.8104}}}],
        }
        points = type("Response", (), {})()
        points.raise_for_status = lambda: None
        points.json = lambda: {"properties": {"forecastHourly": "https://api.weather.gov/gridpoints/BMX/1,1/forecast/hourly"}}
        hourly = type("Response", (), {})()
        hourly.raise_for_status = lambda: None
        hourly.json = lambda: {
            "properties": {
                "periods": [
                    {
                        "startTime": self.event.start_at.replace(minute=0, second=0, microsecond=0).isoformat(),
                        "temperature": 88,
                        "temperatureUnit": "F",
                        "probabilityOfPrecipitation": {"value": 75},
                        "windSpeed": "12 mph",
                        "windDirection": "SW",
                        "shortForecast": "Thunderstorms Likely",
                    }
                ]
            }
        }
        get.side_effect = [geocode, points, hourly]

        route = type("Response", (), {})()
        route.raise_for_status = lambda: None
        route.json = lambda: {
            "routes": [
                {
                    "duration": "4200s",
                    "staticDuration": "3300s",
                    "distanceMeters": 145000,
                }
            ]
        }
        post.return_value = route

        plan = build_travel_plan(self.event, 32.3668, -86.3000)
        self.assertEqual(plan["route"]["status"], "READY")
        self.assertEqual(plan["route"]["traffic_delay_seconds"], 900)
        self.assertEqual(plan["weather"]["status"], "READY")
        self.assertEqual(plan["weather"]["risk"], "HIGH")
        self.assertTrue(any("Traffic is adding" in row for row in plan["recommendations"]))
        self.assertTrue(any("High weather risk" in row for row in plan["recommendations"]))
