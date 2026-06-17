from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import CustomerHealthProfile


class CustomerHealthProfileTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="health-user",
            email="health-user@example.com",
            password="testpass123",
        )
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_get_me_creates_profile(self):
        response = self.client.get("/api/v1/customer-health/me/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(CustomerHealthProfile.objects.count(), 1)
        self.assertEqual(response.data["profile_json"], {})
        self.assertEqual(response.data["workouts_json"], [])

    def test_patch_me_updates_health_data(self):
        payload = {
            "profile_json": {
                "primary_goal": "Strength",
                "training_days": "4",
            },
            "snapshot_json": {
                "readiness": "Ready",
                "steps": "6500",
            },
            "workouts_json": [
                {
                    "id": "w-1",
                    "name": "Strength Day A",
                }
            ],
            "history_json": [
                {
                    "id": "h-1",
                    "workout_name": "Strength Day A",
                }
            ],
            "progress_json": [
                {
                    "id": "p-1",
                    "weight": "210",
                }
            ],
            "devices_json": [
                {
                    "id": "apple-health",
                    "status": "Manual tracking active",
                }
            ],
        }

        response = self.client.patch(
            "/api/v1/customer-health/me/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["profile_json"]["primary_goal"], "Strength")
        self.assertEqual(response.data["snapshot_json"]["readiness"], "Ready")
        self.assertEqual(response.data["workouts_json"][0]["name"], "Strength Day A")

    def test_requires_authentication(self):
        anon = APIClient()
        response = anon.get("/api/v1/customer-health/me/")
        self.assertEqual(response.status_code, 401)