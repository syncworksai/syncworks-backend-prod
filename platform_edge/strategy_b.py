from __future__ import annotations

from typing import Any

from .strategy_a import _fair_away, _parse_ts, _pregame_ask
from .live_data import get_live_mlb_board


def _side_row(game: dict[str, Any], team_key: str, pregame_away: float) -> dict[str, Any] | None:
    team = game[team_key]
    market = game.get(f"{team_key}_market")
    if not market or market.get("yes_ask_cents") is None:
        return None

    away_score = int(game["away"].get("score") or 0)
    home_score = int(game["home"].get("score") or 0)
    inning = int(game.get("inning") or 0)
    outs = int(game.get("outs") or 0)
    half = str(game.get("inning_half") or "")
    fair_away = _fair_away(pregame_away, away_score, home_score, inning, half, outs)
    fair = fair_away if team_key == "away" else 1 - fair_away
    pregame = pregame_away if team_key == "away" else 1 - pregame_away
    score = away_score if team_key == "away" else home_score
    opponent_score = home_score if team_key == "away" else away_score
    trailing = score < opponent_score
    deficit = opponent_score - score if trailing else 0
    batting = (team_key == "away" and half.lower() == "top") or (team_key == "home" and half.lower() == "bottom")
    ask = int(market["yes_ask_cents"])
    bid = market.get("yes_bid_cents")
    drop = round(pregame * 100 - ask, 2)
    edge = round(fair * 100 - ask, 2)

    qualifies = bool(
        game.get("is_live")
        and 45 <= pregame * 100 < 55
        and trailing
        and deficit == 1
        and 4 <= inning <= 6
        and drop >= 10
        and edge >= 3
        and batting
    )

    return {
        "ticker": market.get("ticker"),
        "game_pk": game.get("game_pk"),
        "matchup": f"{game['away'].get('code')} @ {game['home'].get('code')}",
        "team_code": team.get("code"),
        "side": f"{team.get('code')} YES",
        "game_state": game.get("game_state"),
        "pregame_probability_pct": round(pregame * 100, 2),
        "current_ask_cents": ask,
        "current_bid_cents": bid,
        "market_drop_pct": drop,
        "model_probability_pct": round(fair * 100, 2),
        "model_edge_pct": edge,
        "deficit": deficit,
        "inning": inning,
        "inning_half": half,
        "outs": outs,
        "batting": batting,
        "qualifies": qualifies,
        "paper_exit_minutes": 30,
        "strategy": "EDGE Strategy B",
        "strategy_code": "B",
        "strategy_version": "1.0-paper",
        "reason": "45–55% pregame side, down 1 in innings 4–6, >=10pt market drop, >=3pt model edge, batting" if qualifies else None,
    }


def get_strategy_b_live_board() -> dict[str, Any]:
    board = get_live_mlb_board()
    signals = []
    for game in board.get("games", []):
        game_start_ts = _parse_ts(game.get("game_date"))
        if not game_start_ts:
            continue
        away_market = game.get("away_market") or {}
        home_market = game.get("home_market") or {}
        away_ticker = away_market.get("ticker")
        home_ticker = home_market.get("ticker")
        if not away_ticker or not home_ticker:
            continue
        away_pre = _pregame_ask(away_ticker, game_start_ts)
        home_pre = _pregame_ask(home_ticker, game_start_ts)
        if away_pre is None or home_pre is None or away_pre + home_pre <= 0:
            continue
        pregame_away = away_pre / (away_pre + home_pre)
        for key in ("away", "home"):
            row = _side_row(game, key, pregame_away)
            if row:
                signals.append(row)
    signals.sort(key=lambda x: (x["qualifies"], x["model_edge_pct"]), reverse=True)
    return {
        "strategy": {
            "name": "EDGE Strategy B",
            "status": "paper_validation",
            "live_money_enabled": False,
            "historical_result": {
                "development_roi_pct": 12.76,
                "validation_roi_pct": 7.80,
                "final_holdout_roi_pct": 2.36,
                "final_holdout_trades": 9,
            },
            "rule": {
                "pregame_probability_pct": [45, 55],
                "deficit_runs": [1],
                "innings": [4, 6],
                "minimum_market_drop_pct": 10,
                "minimum_model_edge_pct": 3,
                "must_be_batting": True,
                "paper_exit_minutes": 30,
            },
        },
        "source": board.get("source"),
        "refresh_seconds": 10,
        "games": board.get("games", []),
        "signals": signals,
        "qualifying_signals": [x for x in signals if x["qualifies"]],
    }
