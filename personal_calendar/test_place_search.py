from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase


User = get_user_model()


class CalendarPlaceSearchTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="place-search-user",
            email="place-search@example.com",
            password="test-password-123",
        )
        token, _ = Token.objects.get_or_create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_short_search_is_rejected(self):
        response = self.client.get("/api/v1/personal-calendar/places/search/", {"q": "ab"})
        self.assertEqual(response.status_code, 400)

    @patch("personal_calendar.place_search.requests.get")
    def test_address_result_is_normalized(self, mocked_get):
        upstream = Mock()
        upstream.raise_for_status.return_value = None
        upstream.json.return_value = [
            {
                "place_id": 101,
                "display_name": "8700 Minnie Brown Road, Montgomery, Alabama, 36117, United States",
                "lat": "32.3501",
                "lon": "-86.1452",
                "address": {
                    "house_number": "8700",
                    "road": "Minnie Brown Road",
                    "city": "Montgomery",
                    "state": "Alabama",
                    "postcode": "36117",
                    "country": "United States",
                },
            }
        ]
        mocked_get.return_value = upstream

        response = self.client.get(
            "/api/v1/personal-calendar/places/search/",
            {"q": "8700 Minnie Brown Road"},
        )

        self.assertEqual(response.status_code, 200)
        result = response.data["results"][0]
        self.assertEqual(result["address_line1"], "8700 Minnie Brown Road")
        self.assertEqual(result["city"], "Montgomery")
        self.assertEqual(result["state"], "Alabama")
        self.assertEqual(result["postal_code"], "36117")
        self.assertAlmostEqual(result["latitude"], 32.3501)
        self.assertAlmostEqual(result["longitude"], -86.1452)
