from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient


class EdgePortfolioRiskTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="edge-portfolio", email="portfolio@example.com", password="test-pass")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @patch("platform_edge.portfolio_views.get_strategy_b_live_board")
    @patch("platform_edge.portfolio_views.get_strategy_a_live_board")
    def test_portfolio_live_exposes_hard_risk_rules(self, strategy_a, strategy_b):
        strategy_a.return_value = {"signals": [], "qualifying_signals": []}
        strategy_b.return_value = {"signals": [], "qualifying_signals": []}
        response = self.client.get("/api/v1/edge/portfolio/live/?bankroll_cents=10000")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["portfolio"]["daily_limit_cents"], 100)
        self.assertEqual(response.data["rules"]["daily_risk_cap_pct"], 1.0)
        self.assertEqual(response.data["rules"]["per_game_risk_cap_pct"], 0.5)
        self.assertFalse(response.data["rules"]["averaging_down"])
        self.assertTrue(response.data["rules"]["reentry_requires_new_game_state"])
        self.assertFalse(response.data["live_money_enabled"])

    @patch("platform_edge.portfolio_views.get_strategy_b_live_board")
    @patch("platform_edge.portfolio_views.get_strategy_a_live_board")
    def test_first_entry_uses_quarter_percent_and_same_state_does_not_reenter(self, strategy_a, strategy_b):
        item = {
            "ticker": "KXMLBGAME-TEST-ATL",
            "game_pk": 1,
            "matchup": "ATL @ MIA",
            "side": "ATL YES",
            "game_state": "Top 5 • 1 out",
            "current_ask_cents": 30,
            "current_bid_cents": 29,
            "model_probability_pct": 40,
            "model_edge_pct": 10,
            "deficit": 1,
            "inning": 5,
        }
        strategy_a.return_value = {"signals": [item], "qualifying_signals": [item]}
        strategy_b.return_value = {"signals": [], "qualifying_signals": []}

        first = self.client.post("/api/v1/edge/portfolio/paper/tick/", {"bankroll_cents": 10000}, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(len(first.data["opened"]), 1)
        self.assertEqual(first.data["opened"][0]["risk_cents"], 25)

        second = self.client.post("/api/v1/edge/portfolio/paper/tick/", {"bankroll_cents": 10000}, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(second.data["opened"]), 0)
        self.assertTrue(any(x["reason"] in {"market_already_has_open_position", "same_game_state_already_traded"} for x in second.data["skipped"]))
