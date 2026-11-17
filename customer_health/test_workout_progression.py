from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import CustomerHealthProfile
from .workout_progression import build_profile_progression

URL = "/api/v1/customer-health/workout-sessions/progression/"


def session(identifier, reps=12, weight=100, rpe=7, pain=0):
    return {
        "id": identifier, "status": "completed", "finished_at": f"2026-11-{int(identifier):02d}T12:00:00Z",
        "exercises": [{"name": "Barbell Bench Press", "set_logs": [
            {"actual_weight": weight, "actual_reps": reps, "rpe": rpe, "pain_score": pain, "completed": True},
            {"actual_weight": weight, "actual_reps": reps, "rpe": rpe, "pain_score": pain, "completed": True},
        ]}],
    }


class WorkoutProgressionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="progression-one", password="testpass123")
        self.other = User.objects.create_user(username="progression-two", password="testpass123")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Token " + Token.objects.create(user=self.user).key)

    def test_per_user_isolation_and_stats(self):
        CustomerHealthProfile.objects.create(
            user=self.user, profile_json={"primary_goal": "muscle growth"},
            history_json=[session("01"), session("02")])
        CustomerHealthProfile.objects.create(
            user=self.other, history_json=[session("03", weight=250)])
        result = self.client.get(URL)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["workouts_logged"], 2)
        self.assertEqual(result.data["exercises_tracked"], 1)
        exercise = result.data["exercises"][0]
        self.assertEqual(exercise["suggested_weight"], 105)
        self.assertEqual(exercise["rep_range"], {"min": 8, "max": 12})
        self.assertEqual(exercise["action"], "increase")
        self.assertEqual(exercise["best_logged_weight"], 100)

    def test_hold_when_reps_below_range(self):
        answer = build_profile_progression([session("01", reps=9)], {})
        self.assertEqual(answer["exercises"][0]["suggested_weight"], 100)
        self.assertEqual(answer["exercises"][0]["action"], "repeat")

    def test_avoid_increase_for_pain_or_failure(self):
        pain = build_profile_progression([session("01", pain=3)], {})
        self.assertEqual(pain["exercises"][0]["action"], "review")
        self.assertIsNone(pain["exercises"][0]["suggested_weight"])
        failure = build_profile_progression([session("01", rpe=9.5)], {})
        self.assertEqual(failure["exercises"][0]["action"], "hold")

    def test_new_profile_no_guessed_weights(self):
        result = self.client.get(URL)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["exercises"], [])
        self.assertEqual(result.data["workouts_logged"], 0)

    def test_unauthenticated_rejected(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)

    def test_strength_goal_rep_range(self):
        answer = build_profile_progression([session("01", reps=8)], {"primary_goal": "strength"})
        self.assertEqual(answer["exercises"][0]["rep_range"], {"min": 5, "max": 8})

    def test_skips_incomplete_sessions_and_warmups(self):
        active = session("02")
        active["status"] = "active"
        completed = session("01")
        completed["exercises"][0]["set_logs"].insert(
            0, {"set_type": "warmup", "actual_weight": 20, "actual_reps": 20})
        answer = build_profile_progression([completed, active], {})
        self.assertEqual(answer["workouts_logged"], 1)
        self.assertEqual(answer["exercises"][0]["last_sets"], 2)
