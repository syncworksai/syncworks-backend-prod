from __future__ import annotations

from typing import Any

from .live_data import get_live_mlb_board
from .strategy_a import _parse_ts, _pregame_ask

# Frozen 2026-08-10 from EDGE v1.5 E2 portfolio research.
# These values must not be optimized using forward-paper results.
FROZEN_E_RULES = {
    "E1": {
        "name": "E1",
        "pregame_min_pct": 50.0,
        "pregame_max_pct": 100.0,
        "leader_trigger_cents": 80,
        "max_trigger_inning": 5,
        "hedge_multiple": 0.25,
        "hedge_rebound_target_cents": 5,
        "base_risk_pct": 0.50,
        "historical": {
            "holdout_trades": 46,
            "holdout_roi_pct": 16.78,
            "holdout_positive_pct": 73.91,
            "holdout_max_drawdown_pct_bankroll": -1.147,
        },
    },
    "E2": {
        "name": "E2 PRIME",
        "pregame_min_pct": 50.0,
        "pregame_max_pct": 55.0,
        "leader_trigger_cents": 87,
        "max_trigger_inning": 5,
        "hedge_multiple": 0.10,
        "hedge_rebound_target_cents": 5,
        "base_risk_pct": 0.50,
        "historical": {
            "development_trades": 21,
            "development_roi_pct": 62.69,
            "validation_trades": 16,
            "validation_roi_pct": 55.57,
            "holdout_trades": 11,
            "holdout_roi_pct": 57.31,
            "holdout_positive_pct": 90.91,
            "holdout_max_drawdown_pct_bankroll": -0.483,
        },
    },
}

FREEZE_VERSION = "2026-08-10-v1.5"


def _favorite_context(game: dict[str, Any]) -> dict[str, Any] | None:
    game_start_ts = _parse_ts(game.get("game_date"))
    if not game_start_ts:
        return None
    away_market = game.get("away_market") or {}
    home_market = game.get("home_market") or {}
    away_ticker = away_market.get("ticker")
    home_ticker = home_market.get("ticker")
    if not away_ticker or not home_ticker:
        return None

    away_pre = _pregame_ask(away_ticker, game_start_ts)
    home_pre = _pregame_ask(home_ticker, game_start_ts)
    if away_pre is None or home_pre is None or away_pre + home_pre <= 0:
        return None
    away_prob = 100.0 * away_pre / (away_pre + home_pre)
    favorite_key = "away" if away_prob >= 50.0 else "home"
    dog_key = "home" if favorite_key == "away" else "away"
    favorite_prob = away_prob if favorite_key == "away" else 100.0 - away_prob
    favorite_market = game.get(f"{favorite_key}_market") or {}
    dog_market = game.get(f"{dog_key}_market") or {}
    if favorite_market.get("yes_ask_cents") is None or dog_market.get("yes_ask_cents") is None:
        return None

    return {
        "favorite_key": favorite_key,
        "dog_key": dog_key,
        "favorite_prob": favorite_prob,
        "favorite": game[favorite_key],
        "dog": game[dog_key],
        "favorite_market": favorite_market,
        "dog_market": dog_market,
    }


def get_strategy_e_live_boards(board: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    board = board or get_live_mlb_board()
    rows = {code: [] for code in FROZEN_E_RULES}
    for game in board.get("games", []):
        context = _favorite_context(game)
        if not context:
            continue
        inning = int(game.get("inning") or 0)
        for code, rule in FROZEN_E_RULES.items():
            pre = float(context["favorite_prob"])
            if not (rule["pregame_min_pct"] <= pre < rule["pregame_max_pct"]):
                continue
            ask = int(context["favorite_market"]["yes_ask_cents"])
            rows[code].append({
                "strategy_code": code,
                "strategy": rule["name"],
                "freeze_version": FREEZE_VERSION,
                "game_pk": game.get("game_pk"),
                "matchup": f"{game['away'].get('code')} @ {game['home'].get('code')}",
                "game_state": game.get("game_state"),
                "is_live": bool(game.get("is_live")),
                "status": game.get("status"),
                "inning": inning,
                "favorite_code": context["favorite"].get("code"),
                "dog_code": context["dog"].get("code"),
                "favorite_ticker": context["favorite_market"].get("ticker"),
                "dog_ticker": context["dog_market"].get("ticker"),
                "favorite_ask_cents": ask,
                "favorite_bid_cents": context["favorite_market"].get("yes_bid_cents"),
                "dog_ask_cents": int(context["dog_market"]["yes_ask_cents"]),
                "dog_bid_cents": context["dog_market"].get("yes_bid_cents"),
                "pregame_favorite_probability_pct": round(pre, 2),
                "base_entry_eligible": bool(game.get("is_live") and inning <= 1),
                "hedge_triggered_now": bool(
                    game.get("is_live")
                    and inning <= rule["max_trigger_inning"]
                    and ask >= rule["leader_trigger_cents"]
                ),
                "away_score": int(game["away"].get("score") or 0),
                "home_score": int(game["home"].get("score") or 0),
                "rule": rule,
            })

    return {
        code: {
            "strategy": {
                "name": rule["name"],
                "status": "FROZEN_FORWARD_PAPER",
                "freeze_version": FREEZE_VERSION,
                "live_money_enabled": False,
                "rule": rule,
                "historical_result": rule["historical"],
            },
            "source": board.get("source"),
            "signals": rows[code],
            "qualifying_signals": [row for row in rows[code] if row["base_entry_eligible"]],
        }
        for code, rule in FROZEN_E_RULES.items()
    }
