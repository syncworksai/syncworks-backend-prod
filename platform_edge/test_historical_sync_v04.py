from datetime import date, datetime, timezone
from unittest.mock import patch

from django.test import TestCase

from .historical_sync import _match_markets, _play_states, summarize_replay
from .models import EdgeHistoricalSnapshot


class HistoricalReplayV04Tests(TestCase):
    def test_matches_only_same_game_markets(self):
        markets = [
            {"ticker": "KXMLBGAME-26AUG091900ATL-MIA-ATL", "event_ticker": "KXMLBGAME-26AUG091900ATLMIA", "occurrence_datetime": "2026-08-09T23:00:00Z"},
            {"ticker": "KXMLBGAME-26AUG091900ATL-MIA-MIA", "event_ticker": "KXMLBGAME-26AUG091900ATLMIA", "occurrence_datetime": "2026-08-09T23:00:00Z"},
            {"ticker": "KXMLBGAME-26AUG091900ATL-NYY-ATL", "event_ticker": "KXMLBGAME-26AUG091900ATLNYY", "occurrence_datetime": "2026-08-09T23:00:00Z"},
        ]
        matched = _match_markets(markets, "ATL", "MIA")
        self.assertEqual(len(matched), 2)

    def test_play_state_uses_latest_completed_play(self):
        payload = {
            "gameData": {"datetime": {"dateTime": "2026-08-09T23:00:00Z"}},
            "liveData": {"plays": {"allPlays": [
                {
                    "about": {"endTfs": "20260809_230100", "inning": 1, "halfInning": "top"},
                    "result": {"awayScore": 1, "homeScore": 0},
                    "count": {"outs": 1},
                    "runners": [{"movement": {"end": 1}, "details": {"isOut": False}}],
                },
            ]}},
        }
        times, states, start, end = _play_states(payload)
        self.assertEqual(len(times), 1)
        self.assertEqual(states[0]["away_score"], 1)
        self.assertEqual(states[0]["runners_on_base"], 1)
        self.assertEqual(start, datetime(2026, 8, 9, 23, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 8, 9, 23, 1, tzinfo=timezone.utc))

    def test_summary_reports_observed_rate_and_brier(self):
        observed = datetime(2026, 8, 9, 23, 1, tzinfo=timezone.utc)
        common = dict(
            game_pk=123,
            event_ticker="KXMLBGAME-TEST",
            observed_at=observed,
            away_code="ATL",
            home_code="MIA",
            side_code="ATL",
            away_score=1,
            home_score=3,
            inning=5,
            inning_half="top",
            outs=1,
            runners_on_base=0,
            yes_bid_cents=29,
            yes_ask_cents=30,
            yes_close_cents=30,
            market_result="yes",
            model_probability_bps=4200,
        )
        EdgeHistoricalSnapshot.objects.create(market_ticker="T-1", **common)
        common["market_result"] = "no"
        common["observed_at"] = observed.replace(minute=2)
        EdgeHistoricalSnapshot.objects.create(market_ticker="T-2", **common)
        result = summarize_replay(date(2026, 8, 9), minimum_edge_pct=8)
        self.assertEqual(result["eligible_count"], 2)
        self.assertEqual(result["wins"], 1)
        self.assertEqual(result["losses"], 1)
        self.assertEqual(result["observed_win_rate_pct"], 50.0)
        self.assertIsNotNone(result["brier_score"])
