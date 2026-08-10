from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from .research_model import _model_game, _signal_for_side


class EdgeResearchModelTests(TestCase):
    def test_model_returns_probabilities_that_sum_to_one(self):
        game = {
            "away": {"code": "ATL", "score": 1},
            "home": {"code": "MIA", "score": 3},
            "inning": 5,
            "inning_half": "Top",
            "outs": 1,
            "offense": {"first": {"id": 1}, "second": None, "third": None},
            "game_state": "Top 5 • 1 out",
        }
        away, home, reasons = _model_game(game, {"ATL": 0.55, "MIA": 0.45})
        self.assertAlmostEqual(away + home, 1.0, places=8)
        self.assertGreater(len(reasons), 0)

    def test_signal_uses_experimental_discrepancy_bands(self):
        game = {"game_pk": 1, "away": {"code": "ATL"}, "home": {"code": "MIA"}, "game_state": "Top 5"}
        market = {"ticker": "KXMLBGAME-TEST-ATL", "yes_ask_cents": 30, "yes_bid_cents": 29}
        signal = _signal_for_side("ATL", 0.45, market, game, ["test"], 8)
        self.assertEqual(signal["signal"], "GREEN")
        self.assertEqual(signal["edge_pct"], 15.0)
        self.assertFalse(signal["model_version"] == "EDGE-MLB-v0.1")

    @patch("platform_edge.research_model._season_strengths", return_value={"ATL": 0.55, "MIA": 0.45})
    def test_model_is_not_a_probability_guarantee(self, _strengths):
        game = {
            "away": {"code": "ATL", "score": 0},
            "home": {"code": "MIA", "score": 0},
            "inning": 1,
            "inning_half": "Top",
            "outs": 0,
            "offense": {},
            "game_state": "Top 1",
        }
        away, home, _ = _model_game(game, {"ATL": 0.55, "MIA": 0.45})
        self.assertGreater(away, 0.0)
        self.assertLess(away, 1.0)
        self.assertAlmostEqual(home, 1 - away, places=8)
