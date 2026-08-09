from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import EdgeExchangeConnection, EdgeStrategy


class EdgeSafetyTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="edge-test", email="edge@example.com", password="test-pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_dashboard_defaults_to_paper_and_disarmed(self):
        response = self.client.get("/api/v1/edge/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["mode"], "PAPER")
        self.assertFalse(response.data["live_trading_enabled"])
        self.assertFalse(response.data["automation_enabled"])
        self.assertFalse(response.data["strategy"]["is_armed"])
        self.assertTrue(response.data["strategy"]["never_chase"])

    def test_strategy_update_cannot_arm_automation(self):
        strategy = EdgeStrategy.objects.create(user=self.user, name="Test", sport="MLB")
        response = self.client.patch(
            f"/api/v1/edge/strategies/{strategy.id}/",
            {"execution_mode": "AUTO", "is_armed": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_armed"])

    @patch("platform_edge.views.get_balance")
    def test_kalshi_connect_verifies_and_never_returns_secret(self, get_balance):
        get_balance.return_value = {"balance": 7000, "portfolio_value": 7000}
        private_key = "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----"
        response = self.client.post(
            "/api/v1/edge/exchanges/kalshi/",
            {"environment": "DEMO", "api_key_id": "test-key-id", "private_key": private_key},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["connected"])
        self.assertTrue(response.data["can_read"])
        self.assertFalse(response.data["can_trade"])
        self.assertEqual(response.data["balance_cents"], 7000)
        self.assertNotIn("api_key_id", response.data)
        self.assertNotIn("private_key", response.data)
        self.assertNotIn("encrypted_private_key", response.data)

        connection = EdgeExchangeConnection.objects.get(user=self.user, exchange="KALSHI", environment="DEMO")
        self.assertNotEqual(connection.encrypted_private_key, private_key)
