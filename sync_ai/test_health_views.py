from django.test import TestCase


class ProductionHealthProbeTests(TestCase):
    def test_liveness_is_public_and_safe(self):
        response = self.client.get("/api/v1/sync-ai/health/live/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["probe"], "liveness")

    def test_readiness_checks_database_and_schema(self):
        response = self.client.get("/api/v1/sync-ai/health/ready/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ready")
        self.assertTrue(payload["database"])
        self.assertTrue(payload["schema"])
