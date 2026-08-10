from __future__ import annotations

import math
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import requests

from .live_data import get_live_mlb_board

KALSHI_BASE = "https://external-api.kalshi.com/trade-api/v2"
BASE_RUN = 0.32
LATE_RUN = 0.60


def _logit(p: float) -> float:
    p = max(0.02, min(0.98, p))
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-max(-12, min(12, x))))


def _parse_ts(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp())
    except ValueError:
        return None


def _cents(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=256)
def _pregame_ask(ticker: str, game_start_ts: int) -> int | None:
    url = f"{KALSHI_BASE}/series/KXMLBGAME/markets/{ticker}/candlesticks"
    params = {
        "start_ts": game_start_ts - 10800,
        "end_ts": game_start_ts,
        "period_interval": 1,
    }
    try:
        response = requests.get(url, params=params, timeout=8)
        response.raise_for_status()
        candles = response.json().get("candlesticks", [])
    except requests.RequestException:
        return None
    values = []
    for candle in candles:
        ts = int(candle.get("end_period_ts") or 0)
        yes_ask = candle.get("yes_ask") or {}
        price = _cents(yes_ask.get("close_dollars") if "close_dollars" in yes_ask else yes_ask.get("close"))
        if ts <= game_start_ts and price is not None and 1 <= price <= 99:
            values.append((ts, price))
    return max(values)[1] if values else None


def _fair_away(pregame_away: float, away_score: int, home_score: int, inning: int, half: str, outs: int) -> float:
    completed = (max(1, inning) - 1) * 3 + (3 if str(half).lower() == "bottom" else 0) + outs
    remaining = max(0, 27 - completed)
    fraction_remaining = min(1.0, remaining / 27)
    run_weight = BASE_RUN + (LATE_RUN - BASE_RUN) * (1 - fraction_remaining)
    return _sigmoid(_logit(pregame_away) + (away_score - home_score) * run_weight)


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
    ask = int(market["yes_ask_cents"])
    bid = market.get("yes_bid_cents")
    drop = round(pregame * 100 - ask, 2)
    edge = round(fair * 100 - ask, 2)
    qualifies = bool(
        game.get("is_live")
        and 55 <= pregame * 100 < 65
        and trailing
        and deficit in (1, 2)
        and 4 <= inning <= 6
        and drop >= 18
        and edge >= 5
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
        "outs": outs,
        "qualifies": qualifies,
        "paper_exit_minutes": 20,
        "strategy": "EDGE Strategy A",
        "strategy_version": "1.0-paper",
        "reason": "55–65% pregame side, trailing 1–2 in innings 4–6, >=18pt market drop, >=5pt model edge" if qualifies else None,
    }


def get_strategy_a_live_board() -> dict[str, Any]:
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
            "name": "EDGE Strategy A",
            "status": "paper_validation",
            "live_money_enabled": False,
            "historical_result": {
                "development_roi_pct": 4.78,
                "validation_roi_pct": 10.19,
                "final_holdout_roi_pct": 5.76,
                "final_holdout_trades": 37,
            },
            "rule": {
                "pregame_probability_pct": [55, 65],
                "deficit_runs": [1, 2],
                "innings": [4, 6],
                "minimum_market_drop_pct": 18,
                "minimum_model_edge_pct": 5,
                "paper_exit_minutes": 20,
            },
        },
        "source": board.get("source"),
        "refresh_seconds": 10,
        "games": board.get("games", []),
        "signals": signals,
        "qualifying_signals": [x for x in signals if x["qualifies"]],
    }
