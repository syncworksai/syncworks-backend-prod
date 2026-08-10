from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import requests

from .research_model import _model_game

SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"


def _dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _fetch_schedule(day: date) -> list[dict[str, Any]]:
    try:
        r = requests.get(SCHEDULE_URL, params={"sportId": 1, "date": day.isoformat(), "hydrate": "linescore"}, timeout=8)
        r.raise_for_status()
        return r.json().get("dates", [{}])[0].get("games", []) if r.json().get("dates") else []
    except requests.RequestException:
        return []


def _fetch_feed(game_pk: int) -> dict[str, Any] | None:
    try:
        r = requests.get(FEED_URL.format(game_pk=game_pk), timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


def _sample_game_states(feed: dict[str, Any]) -> list[dict[str, Any]]:
    game_data = feed.get("gameData", {})
    live = feed.get("liveData", {})
    teams = game_data.get("teams", {})
    away = teams.get("away", {})
    home = teams.get("home", {})
    away_code = away.get("abbreviation") or away.get("name", "AWY")[:3].upper()
    home_code = home.get("abbreviation") or home.get("name", "HOM")[:3].upper()
    game_pk = feed.get("gamePk")
    plays = live.get("plays", {}).get("allPlays", [])
    final_linescore = live.get("linescore", {})
    outcome_away = int((final_linescore.get("teams", {}).get("away", {}) or {}).get("runs") or 0)
    outcome_home = int((final_linescore.get("teams", {}).get("home", {}) or {}).get("runs") or 0)
    rows: list[dict[str, Any]] = []
    # Sample after every play. This preserves score, inning, outs, and base state
    # without pretending we have an exchange price from the historical market.
    for play in plays:
        about = play.get("about", {})
        result = play.get("result", {})
        if not about.get("isComplete"):
            continue
        inning = int(about.get("inning") or 0)
        half = str(about.get("halfInning") or "")
        if inning <= 0 or inning > 9:
            continue
        runners = {"first": None, "second": None, "third": None}
        for runner in play.get("runners", []):
            movement = runner.get("movement", {})
            end = movement.get("end")
            details = runner.get("details", {})
            if end in runners and not details.get("isOut"):
                runners[end] = {"id": details.get("runner", {}).get("id")}
        score = play.get("score", {})
        game = {
            "game_pk": game_pk,
            "away": {"code": away_code, "score": int(score.get("awayScore") or 0)},
            "home": {"code": home_code, "score": int(score.get("homeScore") or 0)},
            "inning": inning,
            "inning_half": "Top" if half.lower() == "top" else "Bottom",
            "outs": int(about.get("outs") or 0),
            "offense": runners,
            "game_state": f"{half} {inning} • {int(about.get('outs') or 0)} out",
        }
        rows.append({"game": game, "away_won": outcome_away > outcome_home})
    return rows


def run_mlb_backtest(start: date, end: date, max_games: int = 250) -> dict[str, Any]:
    states: list[dict[str, Any]] = []
    games_seen = 0
    for day in _dates(start, end):
        for game_meta in _fetch_schedule(day):
            if game_meta.get("status", {}).get("abstractGameState") != "Final":
                continue
            if games_seen >= max_games:
                break
            feed = _fetch_feed(int(game_meta["gamePk"]))
            if not feed:
                continue
            rows = _sample_game_states(feed)
            states.extend(rows)
            games_seen += 1
        if games_seen >= max_games:
            break

    # Use league-neutral strength for the first calibration pass. Team strength
    # is deliberately excluded here so the UI can separately report the
    # pure in-game comeback relationship without leakage from final outcomes.
    strengths: dict[str, float] = {}
    buckets: dict[str, list[dict[str, float]]] = defaultdict(list)
    for row in states:
        game = row["game"]
        away_p, home_p, _ = _model_game(game, strengths)
        actual = 1.0 if row["away_won"] else 0.0
        score_diff = int(game["away"]["score"]) - int(game["home"]["score"])
        inning = int(game["inning"])
        key = f"{abs(score_diff)}-run / {inning}th"
        buckets[key].append({"pred": away_p, "actual": actual})

    bucket_rows = []
    for key, values in sorted(buckets.items()):
        n = len(values)
        predicted = sum(v["pred"] for v in values) / n
        actual = sum(v["actual"] for v in values) / n
        bucket_rows.append({
            "bucket": key,
            "samples": n,
            "predicted_away_win_pct": round(predicted * 100, 1),
            "actual_away_win_pct": round(actual * 100, 1),
            "calibration_gap_pct": round((actual - predicted) * 100, 1),
        })

    brier = None
    if states:
        # Recompute predictions for a simple overall Brier score.
        errors = []
        for row in states:
            away_p, _, _ = _model_game(row["game"], strengths)
            errors.append((away_p - (1.0 if row["away_won"] else 0.0)) ** 2)
        brier = round(sum(errors) / len(errors), 5)

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "games": games_seen,
        "states": len(states),
        "brier_score": brier,
        "buckets": bucket_rows,
        "limitations": [
            "Historical MLB game states are used; historical Kalshi prices are not included in this pass.",
            "No strategy profitability claim is made until market-price history, fees, spreads, and execution assumptions are added.",
            "Model probabilities are experimental and should be calibrated on held-out data before any live use.",
        ],
    }
