from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import CustomerHealthProfile


class HealthWorkoutPersistenceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="workout-persistence-user",
            email="workout-persistence@example.com",
            password="testpass123",
        )
        token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_save_active_then_complete_workout(self):
        session = {
            "id": "session-1",
            "status": "active",
            "workout_name": "Push Day",
            "exercises": [],
        }

        active_response = self.client.put(
            "/api/v1/customer-health/workout-sessions/active/",
            {
                "session": session,
                "planner_item_id": "planner-1",
                "workout_id": "workout-1",
            },
            format="json",
        )
        self.assertEqual(active_response.status_code, 200)
        self.assertEqual(
            active_response.data["active_workout"]["session"]["id"],
            "session-1",
        )

        completed = {
            **session,
            "status": "completed",
            "finished_at": "2026-08-18T12:00:00Z",
        }
        complete_response = self.client.post(
            "/api/v1/customer-health/workout-sessions/",
            {"session": completed},
            format="json",
        )
        self.assertEqual(complete_response.status_code, 200)
        self.assertEqual(complete_response.data["count"], 1)

        profile = CustomerHealthProfile.objects.get(user=self.user)
        self.assertEqual(profile.history_json[0]["id"], "session-1")
        self.assertNotIn("_active_workout", profile.snapshot_json)

    def test_completed_session_is_upserted_not_duplicated(self):
        first = {
            "id": "session-upsert",
            "status": "completed",
            "workout_name": "Pull Day",
            "completed_sets": 10,
        }
        second = {
            **first,
            "completed_sets": 12,
        }

        response_one = self.client.post(
            "/api/v1/customer-health/workout-sessions/",
            {"session": first},
            format="json",
        )
        response_two = self.client.post(
            "/api/v1/customer-health/workout-sessions/",
            {"session": second},
            format="json",
        )

        self.assertEqual(response_one.status_code, 200)
        self.assertEqual(response_two.status_code, 200)
        self.assertEqual(response_two.data["count"], 1)

        profile = CustomerHealthProfile.objects.get(user=self.user)
        self.assertEqual(len(profile.history_json), 1)
        self.assertEqual(profile.history_json[0]["completed_sets"], 12)

    def test_get_and_clear_active_workout(self):
        session = {
            "id": "session-active",
            "status": "active",
            "workout_name": "Leg Day",
        }
        self.client.put(
            "/api/v1/customer-health/workout-sessions/active/",
            {"session": session},
            format="json",
        )

        get_response = self.client.get(
            "/api/v1/customer-health/workout-sessions/active/"
        )
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(
            get_response.data["active_workout"]["session"]["id"],
            "session-active",
        )

        delete_response = self.client.delete(
            "/api/v1/customer-health/workout-sessions/active/"
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertTrue(delete_response.data["cleared"])

        get_after = self.client.get(
            "/api/v1/customer-health/workout-sessions/active/"
        )
        self.assertIsNone(get_after.data["active_workout"])

    def test_requires_authentication(self):
        anon = APIClient()
        self.assertEqual(
            anon.get("/api/v1/customer-health/workout-sessions/").status_code,
            401,
        )
        self.assertEqual(
            anon.get("/api/v1/customer-health/workout-sessions/active/").status_code,
            401,
        )
