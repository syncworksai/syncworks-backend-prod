from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

URL = "/api/v1/sync-ai/assist/pilot/daily/"

class DailyAssistantTests(TestCase):
    def setUp(self):
        U = get_user_model()
        self.pilot = U.objects.create_user(username="daily-pilot", email="jacoblord7@outlook.com", password="unit-test-password")
        self.client = APIClient()
        self.client.force_authenticate(self.pilot)

    def test_daily_and_status(self):
        first = self.client.get(URL)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["connections"]["outlook_in_syncworks"], "not_connected")
        self.assertFalse(first.data["can_send"])
        created = self.client.post(URL, {"title": "Review property email", "priority": "HIGH", "category": "PROPERTY"}, format="json")
        self.assertEqual(created.status_code, 201)
        task = created.data["items"][0]
        self.assertEqual(task["status"], "OPEN")
        done = self.client.post(URL+"item/", {"id": task["id"], "status": "DONE"}, format="json")
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.data["summary"]["done"], 1)
        missing = self.client.post(URL+"item/", {"id": "manual:missing", "status": "DONE"}, format="json")
        self.assertEqual(missing.status_code, 404)
