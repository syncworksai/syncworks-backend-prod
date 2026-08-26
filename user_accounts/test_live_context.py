from django.test import SimpleTestCase

from user_accounts.views.live_context import _normalize_route, _normalize_weather


class LiveContextNormalizationTests(SimpleTestCase):
    def test_weather_normalization_includes_minute_precipitation(self):
        payload = {
            "timezone": "America/Chicago",
            "timezone_offset": -18000,
            "current": {
                "dt": 100,
                "temp": 82.4,
                "feels_like": 85.1,
                "humidity": 70,
                "wind_speed": 5,
                "visibility": 16093.44,
                "weather": [{"main": "Rain", "description": "light rain", "icon": "10d"}],
            },
            "minutely": [
                {"dt": 100, "precipitation": 0},
                {"dt": 160, "precipitation": 0.25},
            ],
            "hourly": [
                {"dt": 100, "temp": 82, "feels_like": 84, "pop": 0.6, "wind_speed": 4, "weather": [{"main": "Rain", "description": "rain", "icon": "10d"}]},
            ],
            "alerts": [],
        }

        result = _normalize_weather(payload, 32.3, -86.3)

        self.assertTrue(result["available"])
        self.assertTrue(result["minute_forecast"]["available"])
        self.assertEqual(result["minute_forecast"]["next_precipitation"]["timestamp"], 160)
        self.assertEqual(result["hourly"][0]["precip_probability"], 60)
        self.assertAlmostEqual(result["current"]["wind_mph"], 11.2)

    def test_route_normalization_calculates_live_delay(self):
        route = {
            "duration": 4200,
            "duration_typical": 3600,
            "distance": 80467.2,
            "weight": 4200,
            "legs": [],
        }

        result = _normalize_route(route, 0)

        self.assertEqual(result["duration_minutes"], 70)
        self.assertEqual(result["typical_duration_minutes"], 60)
        self.assertEqual(result["delay_minutes"], 10)
        self.assertEqual(result["distance_miles"], 50.0)
