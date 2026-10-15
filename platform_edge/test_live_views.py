from unittest.mock import patch

from django.test import SimpleTestCase

from .live_views import _football_board


class _Request:
    def __init__(self, **params):
        self.query_params = params


class FootballSlateViewTests(SimpleTestCase):
    @patch("platform_edge.live_views.get_football_board")
    def test_explicit_date_is_sent_as_single_scoreboard_day(self, get_board):
        get_board.return_value = {"games": [{"game_pk": "1"}], "signals": []}

        result = _football_board(_Request(date="2026-10-03"), "NCAAF", 5.0)

        get_board.assert_called_once_with("NCAAF", "2026-10-03", 5.0)
        self.assertEqual(result["slate_date"], "2026-10-03")
        self.assertFalse(result["slate_is_upcoming"])

    @patch("platform_edge.live_views.get_football_board")
    def test_default_walks_forward_until_games_exist(self, get_board):
        get_board.side_effect = [
            {"games": [], "signals": []},
            {"games": [{"game_pk": "2"}], "signals": []},
        ]

        result = _football_board(_Request(), "NFL", 5.0, lookahead_days=2)

        self.assertEqual(get_board.call_count, 2)
        first_date = get_board.call_args_list[0].args[1]
        second_date = get_board.call_args_list[1].args[1]
        self.assertRegex(first_date, r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(second_date, r"^\d{4}-\d{2}-\d{2}$")
        self.assertNotEqual(first_date, second_date)
        self.assertTrue(result["slate_is_upcoming"])
        self.assertEqual(result["days_ahead"], 1)
