from datetime import datetime, timezone

from django.test import TestCase

from .backtest import run_mlb_backtest
from .models import EdgeHistoricalSnapshot


class EdgeBacktestV05Tests(TestCase):
    def setUp(self):
        observed = datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc)
        EdgeHistoricalSnapshot.objects.create(
            game_pk=1,
            market_ticker="KXMLBGAME-TEST-A",
            observed_at=observed,
            away_code="ATL",
            home_code="MIA",
            side_code="ATL",
            away_score=1,
            home_score=3,
            inning=5,
            inning_half="TOP",
            outs=1,
            runners_on_base=1,
            yes_bid_cents=27,
            yes_ask_cents=29,
            yes_close_cents=28,
            market_result="YES",
            model_probability_bps=4000,
        )
        EdgeHistoricalSnapshot.objects.create(
            game_pk=2,
            market_ticker="KXMLBGAME-TEST-B",
            observed_at=observed,
            away_code="NYM",
            home_code="PHI",
            side_code="NYM",
            away_score=0,
            home_score=3,
            inning=7,
            inning_half="TOP",
            outs=2,
            runners_on_base=0,
            yes_bid_cents=5,
            yes_ask_cents=6,
            yes_close_cents=5,
            market_result="NO",
            model_probability_bps=1800,
        )

    def test_backtest_reports_strategy_metrics(self):
        result = run_mlb_backtest()
        self.assertEqual(result["dataset"]["samples"], 2)
        self.assertEqual(len(result["strategies"]), 3)
        self.assertIn("roi_pct", result["strategies"][0])
        self.assertIn("comeback_buckets", result)

    def test_threshold_changes_opportunity_count(self):
        result = run_mlb_backtest()
        counts = [row["opportunities"] for row in result["strategies"]]
        self.assertGreaterEqual(counts[0], counts[1])
        self.assertGreaterEqual(counts[1], counts[2])
