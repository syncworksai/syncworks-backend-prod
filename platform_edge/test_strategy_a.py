from django.test import TestCase

from .strategy_a import _fair_away, _side_row


class StrategyATests(TestCase):
    def test_fair_probability_is_bounded(self):
        p = _fair_away(0.60, 2, 3, 5, "Top", 1)
        self.assertGreater(p, 0)
        self.assertLess(p, 1)

    def test_strategy_a_rule_fields_are_computed(self):
        game = {
            "game_pk": 1,
            "is_live": True,
            "game_state": "Top 5 • 1 out",
            "inning": 5,
            "inning_half": "Top",
            "outs": 1,
            "away": {"code": "ATL", "score": 2},
            "home": {"code": "MIA", "score": 3},
            "away_market": {"ticker": "KXMLBGAME-X-ATL", "yes_ask_cents": 38, "yes_bid_cents": 37},
            "home_market": {"ticker": "KXMLBGAME-X-MIA", "yes_ask_cents": 64, "yes_bid_cents": 62},
        }
        row = _side_row(game, "away", 0.60)
        self.assertEqual(row["deficit"], 1)
        self.assertEqual(row["inning"], 5)
        self.assertEqual(row["pregame_probability_pct"], 60.0)
        self.assertEqual(row["market_drop_pct"], 22.0)
        self.assertEqual(row["strategy"], "EDGE Strategy A")
        expected = row["model_edge_pct"] >= 5
        self.assertEqual(row["qualifies"], expected)
