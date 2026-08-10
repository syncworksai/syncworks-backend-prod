from __future__ import annotations

import math
from datetime import date
from functools import lru_cache
from typing import Any

import requests

from .live_data import TEAM_CODES, get_live_mlb_board

MLB_STANDINGS_URL = "https://statsapi.mlb.com/api/v1/standings"


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-12.0, min(12.0, value))))


def _logit(probability: float) -> float:
    p = max(0.02, min(0.98, probability))
    return math.log(p / (1.0 - p))


@lru_cache(maxsize=2)
def _season_strengths(season: int) -> dict[str, float]:
    params = {
        "leagueId": "103,104",
        "season": season,
        "standingsTypes": "regularSeason",
    }
    try:
        response = requests.get(MLB_STANDINGS_URL, params=params, timeout=6)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException:
        return {}

    strengths: dict[str, float] = {}
    for record in payload.get("records", []):
        for team_record in record.get("teamRecords", []):
            team = team_record.get("team", {})
            code = TEAM_CODES.get(team.get("name")) or team.get("abbreviation")
            wins = int(team_record.get("wins") or 0)
            losses = int(team_record.get("losses") or 0)
            games = wins + losses
            if code and games:
                strengths[code] = wins / games
    return strengths


def _base_count(offense: dict[str, Any]) -> int:
    return sum(1 for key in ("first", "second", "third") if offense.get(key))


def _model_game(game: dict[str, Any], strengths: dict[str, float]) -> tuple[float, float, list[str]]:
    away = game["away"]
    home = game["home"]
    away_code = away.get("code")
    home_code = home.get("code")
    away_strength = strengths.get(away_code, 0.50)
    home_strength = strengths.get(home_code, 0.50)

    # v0.2 is deliberately transparent and conservative. It is a research model,
    # not a calibrated wagering model. Coefficients will be tuned only from held-out data.
    base_logit = _logit(0.50 + 0.55 * (away_strength - home_strength))
    home_advantage = 0.10
    base_logit -= home_advantage  # positive logit means away team

    away_score = float(away.get("score") or 0)
    home_score = float(home.get("score") or 0)
    score_diff = away_score - home_score
    inning = int(game.get("inning") or 0)
    outs = int(game.get("outs") or 0)
    half = str(game.get("inning_half") or "")
    completed_innings = max(0, min(9, inning - 1))
    completed_outs = completed_innings * 3 + outs
    if half.lower() == "bottom":
        completed_outs += 3
    remaining_outs = max(0, 27 - completed_outs)
    leverage = min(1.0, remaining_outs / 27.0)

    # A run is more informative early than late; late score is already close to terminal.
    score_weight = 0.16 + 0.34 * (1.0 - leverage)
    base_logit += score_diff * score_weight

    batting_away = half.lower() == "top"
    batting_code = away_code if batting_away else home_code
    runners = _base_count(game.get("offense") or {})
    base_out_boost = (0.10 * runners) - (0.045 * outs * runners)
    if batting_code == away_code:
        base_logit += base_out_boost
    else:
        base_logit -= base_out_boost

    # Small late-game uncertainty adjustment: do not let the heuristic become extreme.
    base_logit *= 0.72 + 0.28 * leverage
    away_probability = _sigmoid(base_logit)
    home_probability = 1.0 - away_probability

    reasons = [
        f"Season strength: {away_code} {away_strength:.3f} vs {home_code} {home_strength:.3f}",
        f"Live score: {away_code} {int(away_score)}–{int(home_score)} {home_code}",
        f"State: {game.get('game_state') or game.get('status')}; {remaining_outs} estimated outs remain",
    ]
    if runners:
        reasons.append(f"{runners} runner(s) currently on base")
    return away_probability, home_probability, reasons


def _signal_for_side(team_code: str, probability: float, market: dict[str, Any] | None, game: dict[str, Any], reasons: list[str], minimum_edge: float = 8.0) -> dict[str, Any] | None:
    if not market:
        return None
    ask = market.get("yes_ask_cents")
    bid = market.get("yes_bid_cents")
    if ask is None:
        return None
    model_pct = round(probability * 100, 1)
    edge_pct = round(model_pct - float(ask), 1)
    yellow_floor = max(3.0, min(6.0, minimum_edge / 2.0))
    if edge_pct >= minimum_edge:
        signal = "GREEN"
        research_status = "LARGE MODEL/MARKET DISCREPANCY"
    elif edge_pct >= yellow_floor:
        signal = "YELLOW"
        research_status = "SMALL MODEL/MARKET DISCREPANCY"
    else:
        signal = "RED"
        research_status = "NO MATERIAL DISCREPANCY"
    score = max(0, min(100, int(round(50 + edge_pct * 3))))
    return {
        "sport": "MLB",
        "event_key": str(game.get("game_pk")),
        "matchup": f"{game['away'].get('code')} @ {game['home'].get('code')}",
        "game_state": game.get("game_state") or game.get("status"),
        "side": f"{team_code} YES",
        "team_code": team_code,
        "market_ticker": market.get("ticker"),
        "market_price_cents": int(ask),
        "market_bid_cents": bid,
        "model_probability_pct": model_pct,
        "edge_pct": edge_pct,
        "opportunity_score": score,
        "signal": signal,
        "research_status": research_status,
        "model_version": "EDGE-MLB-v0.2-experimental",
        "why": reasons,
        "observed_at": date.today().isoformat(),
    }


def get_mlb_research_board(target_date: str | None = None, minimum_edge: float = 8.0) -> dict[str, Any]:
    board = get_live_mlb_board(target_date)
    strengths = _season_strengths(date.today().year)
    signals: list[dict[str, Any]] = []
    for game in board.get("games", []):
        away_probability, home_probability, reasons = _model_game(game, strengths)
        away_signal = _signal_for_side(game["away"].get("code"), away_probability, game.get("away_market"), game, reasons, minimum_edge)
        home_signal = _signal_for_side(game["home"].get("code"), home_probability, game.get("home_market"), game, reasons, minimum_edge)
        if away_signal:
            signals.append(away_signal)
        if home_signal:
            signals.append(home_signal)
    signals.sort(key=lambda item: item["edge_pct"], reverse=True)
    return {
        **board,
        "model": {
            "version": "EDGE-MLB-v0.2-experimental",
            "status": "research_only",
            "minimum_edge_pct": minimum_edge,
            "calibrated": False,
            "note": "Transparent heuristic. Do not treat as a proven probability model until held-out backtesting is complete.",
        },
        "signals": signals,
    }
