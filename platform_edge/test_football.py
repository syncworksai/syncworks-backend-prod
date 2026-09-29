from django.test import SimpleTestCase

from .football import _match_event, _no_vig_pair, _stake_plan


class FootballEdgeMathTests(SimpleTestCase):
    def test_no_vig_pair_normalizes_moneylines(self):
        away, home = _no_vig_pair(+150, -170)
        self.assertIsNotNone(away)
        self.assertIsNotNone(home)
        self.assertAlmostEqual(away + home, 1.0, places=6)
        self.assertLess(away, home)

    def test_primary_value_band_uses_five_dollar_plan(self):
        plan = _stake_plan(30, 7.0, 5.0)
        self.assertTrue(plan["primary_price_band"])
        self.assertEqual(plan["target_stake_cents"], 500)
        self.assertGreater(plan["contracts"], 0)
        self.assertLessEqual(plan["estimated_cost_cents"], 500)

    def test_strong_primary_band_can_use_seven_fifty_plan(self):
        plan = _stake_plan(35, 12.0, 5.0)
        self.assertEqual(plan["target_stake_cents"], 750)
        self.assertLessEqual(plan["estimated_cost_cents"], 750)

    def test_market_match_uses_names_when_codes_differ(self):
        markets = {"KXNCAAFGAME-26OCT03FLAMIZZ": [
            {"event_ticker": "KXNCAAFGAME-26OCT03FLAMIZZ", "ticker": "KXNCAAFGAME-26OCT03FLAMIZZ-FLA", "title": "Florida vs Missouri", "yes_sub_title": "Florida"},
            {"event_ticker": "KXNCAAFGAME-26OCT03FLAMIZZ", "ticker": "KXNCAAFGAME-26OCT03FLAMIZZ-MIZZ", "title": "Florida vs Missouri", "yes_sub_title": "Missouri"},
        ]}
        away = {"code": "FLA", "market_code": "FLA", "name": "Florida Gators", "short_name": "Florida", "location": "Florida"}
        home = {"code": "MIZ", "market_code": "MIZ", "name": "Missouri Tigers", "short_name": "Missouri", "location": "Missouri"}
        self.assertEqual(_match_event(markets, away, home), "KXNCAAFGAME-26OCT03FLAMIZZ")
