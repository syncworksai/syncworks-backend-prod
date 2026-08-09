from __future__ import annotations

import math
from datetime import date
from typing import Any

import requests

MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
KALSHI_MARKETS_URL = "https://external-api.kalshi.com/trade-api/v2/markets"

TEAM_CODES = {
    "Arizona Diamondbacks": "ARI",
    "Athletics": "ATH",
    "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYM",
    "New York Yankees": "NYY",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",
    "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}


def _cents(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


def _record(team_side: dict[str, Any]) -> dict[str, Any]:
    record = team_side.get("leagueRecord") or {}
    wins = int(record.get("wins") or 0)
    losses = int(record.get("losses") or 0)
    games = wins + losses
    pct = wins / games if games else 0.5
    return {"wins": wins, "losses": losses, "pct": round(pct, 4)}


def _mlb_games(target_date: str | None = None) -> list[dict[str, Any]]:
    params = {
        "sportId": 1,
        "date": target_date or date.today().isoformat(),
        "hydrate": "linescore,probablePitcher,team",
    }
    response = requests.get(MLB_SCHEDULE_URL, params=params, timeout=8)
    response.raise_for_status()
    payload = response.json()
    games: list[dict[str, Any]] = []

    for day in payload.get("dates", []):
        for game in day.get("games", []):
            teams = game.get("teams", {})
            away = teams.get("away", {})
            home = teams.get("home", {})
            away_name = away.get("team", {}).get("name", "Away")
            home_name = home.get("team", {}).get("name", "Home")
            linescore = game.get("linescore") or {}
            inning = linescore.get("currentInning")
            inning_ordinal = linescore.get("currentInningOrdinal")
            inning_half = linescore.get("inningHalf")
            outs = linescore.get("outs")
            offense = linescore.get("offense") or {}
            defense = linescore.get("defense") or {}
            status = game.get("status", {})
            detailed_state = status.get("detailedState") or status.get("abstractGameState") or "Scheduled"

            if inning_ordinal:
                game_state = f"{inning_half or ''} {inning_ordinal}".strip()
                if outs is not None:
                    game_state += f" • {outs} out{'s' if outs != 1 else ''}"
            else:
                game_state = detailed_state

            games.append(
                {
                    "game_pk": game.get("gamePk"),
                    "game_date": game.get("gameDate"),
                    "status": detailed_state,
                    "is_live": status.get("abstractGameState") == "Live",
                    "away": {
                        "name": away_name,
                        "code": TEAM_CODES.get(away_name, away.get("team", {}).get("abbreviation")),
                        "score": away.get("score", 0),
                        "probable_pitcher": away.get("probablePitcher", {}).get("fullName"),
                        "record": _record(away),
                    },
                    "home": {
                        "name": home_name,
                        "code": TEAM_CODES.get(home_name, home.get("team", {}).get("abbreviation")),
                        "score": home.get("score", 0),
                        "probable_pitcher": home.get("probablePitcher", {}).get("fullName"),
                        "record": _record(home),
                    },
                    "inning": inning,
                    "inning_half": inning_half,
                    "outs": outs,
                    "game_state": game_state,
                    "offense": offense,
                    "defense": defense,
                }
            )
    return games


def _kalshi_mlb_markets() -> list[dict[str, Any]]:
    params = {
        "series_ticker": "KXMLBGAME",
        "status": "open",
        "limit": 1000,
        "mve_filter": "exclude",
    }
    response = requests.get(KALSHI_MARKETS_URL, params=params, timeout=8)
    response.raise_for_status()
    return response.json().get("markets", [])


def _market_by_team(markets: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for market in markets:
        ticker = str(market.get("ticker") or "")
        event_ticker = str(market.get("event_ticker") or "")
        team_code = ticker.rsplit("-", 1)[-1].upper() if "-" in ticker else ""
        if event_ticker and team_code:
            indexed[(event_ticker, team_code)] = market
    return indexed


def _same_game_event(markets: list[dict[str, Any]], away_code: str | None, home_code: str | None) -> str | None:
    if not away_code or not home_code:
        return None
    away_code = away_code.upper()
    home_code = home_code.upper()
    for market in markets:
        event_ticker = str(market.get("event_ticker") or "")
        if not event_ticker.startswith("KXMLBGAME-"):
            continue
        suffix = event_ticker.rsplit("-", 1)[-1].upper()
        if away_code in suffix and home_code in suffix:
            return event_ticker
    return None


def _market_view(market: dict[str, Any] | None) -> dict[str, Any] | None:
    if not market:
        return None
    return {
        "ticker": market.get("ticker"),
        "yes_bid_cents": _cents(market.get("yes_bid_dollars")),
        "yes_ask_cents": _cents(market.get("yes_ask_dollars")),
        "no_bid_cents": _cents(market.get("no_bid_dollars")),
        "no_ask_cents": _cents(market.get("no_ask_dollars")),
        "last_price_cents": _cents(market.get("last_price_dollars")),
        "volume": market.get("volume_fp"),
        "liquidity_dollars": market.get("liquidity_dollars"),
        "status": market.get("status"),
    }


def _logit(probability: float) -> float:
    p = min(0.97, max(0.03, probability))
    return math.log(p / (1 - p))


def _logistic(value: float) -> float:
    return 1 / (1 + math.exp(-value))


def _base_runner_count(offense: dict[str, Any]) -> int:
    return sum(1 for key in ("first", "second", "third") if offense.get(key))


def _game_progress(game: dict[str, Any]) -> float:
    inning = int(game.get("inning") or 0)
    if inning <= 0:
        return 0.0
    half = str(game.get("inning_half") or "Top").lower()
    outs = min(3, max(0, int(game.get("outs") or 0)))
    completed_half_innings = max(0, (inning - 1) * 2 + (1 if half.startswith("bottom") else 0))
    progress = (completed_half_innings * 3 + outs) / 54
    return min(0.98, max(0.0, progress))


def _live_fair_probabilities(game: dict[str, Any]) -> tuple[float, float, list[str]]:
    away_pct = float(game["away"].get("record", {}).get("pct") or 0.5)
    home_pct = float(game["home"].get("record", {}).get("pct") or 0.5)

    # v0.1 baseline: season strength differential, shrunk toward 50%, plus home-field advantage.
    pregame_logit = 0.65 * (_logit(away_pct) - _logit(home_pct)) - 0.12
    progress = _game_progress(game)
    score_diff = int(game["away"].get("score") or 0) - int(game["home"].get("score") or 0)

    # A run becomes progressively more valuable as remaining outs disappear.
    score_leverage = 0.55 + (1.15 * progress)
    live_logit = pregame_logit + (score_diff * score_leverage)

    runners = _base_runner_count(game.get("offense") or {})
    outs = min(3, max(0, int(game.get("outs") or 0)))
    if game.get("is_live") and runners:
        threat = runners * 0.16 * max(0.15, 1 - (outs / 3))
        batting_away = str(game.get("inning_half") or "").lower().startswith("top")
        live_logit += threat if batting_away else -threat

    away_fair = min(0.985, max(0.015, _logistic(live_logit)))
    home_fair = 1 - away_fair

    reasons = [
        f"Season strength {game['away']['record']['wins']}-{game['away']['record']['losses']} vs {game['home']['record']['wins']}-{game['home']['record']['losses']}",
        f"Score impact {score_diff:+d} run(s) with {round((1 - progress) * 54)} game-outs remaining",
    ]
    if runners:
        reasons.append(f"{runners} runner{'s' if runners != 1 else ''} on with {outs} out{'s' if outs != 1 else ''}")
    else:
        reasons.append("No current baserunner threat adjustment")
    return away_fair, home_fair, reasons


def _signal_for_side(team_code: str | None, fair: float, market: dict[str, Any] | None, game: dict[str, Any], reasons: list[str]) -> dict[str, Any] | None:
    if not team_code or not market:
        return None
    ask = market.get("yes_ask_cents")
    bid = market.get("yes_bid_cents")
    if ask is None:
        return None

    fair_pct = round(fair * 100, 1)
    edge = round(fair_pct - ask, 1)
    if edge >= 8:
        signal = "GREEN"
        action = "STRONG ENTRY" if edge >= 10 else "ENTRY"
    elif edge >= 3:
        signal = "YELLOW"
        action = "WATCH"
    else:
        signal = "RED"
        action = "TOO LATE" if edge < 0 else "PASS"

    max_entry = max(1, min(99, int(math.floor(fair_pct - 3))))
    score = max(0, min(100, int(round(50 + edge * 4))))
    return {
        "id": f"{game.get('game_pk')}-{team_code}",
        "sport": "MLB",
        "matchup": f"{game['away'].get('code')} @ {game['home'].get('code')}",
        "game_state": game.get("game_state"),
        "side": f"{team_code} YES",
        "team_code": team_code,
        "market_price_cents": ask,
        "market_bid_cents": bid,
        "model_probability_pct": fair_pct,
        "edge_pct": edge,
        "opportunity_score": score,
        "signal": signal,
        "action": action,
        "max_entry_cents": max_entry,
        "is_live": bool(game.get("is_live")),
        "model_version": "MLB-LIVE-v0.1",
        "experimental": True,
        "why": reasons,
    }


def get_live_mlb_board(target_date: str | None = None) -> dict[str, Any]:
    games = _mlb_games(target_date)
    try:
        markets = _kalshi_mlb_markets()
        market_error = None
    except requests.RequestException as exc:
        markets = []
        market_error = str(exc)

    index = _market_by_team(markets)
    rows: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []

    for game in games:
        away_code = game["away"].get("code")
        home_code = game["home"].get("code")
        event_ticker = _same_game_event(markets, away_code, home_code)
        away_market_raw = index.get((event_ticker, str(away_code).upper())) if event_ticker and away_code else None
        home_market_raw = index.get((event_ticker, str(home_code).upper())) if event_ticker and home_code else None
        away_market = _market_view(away_market_raw)
        home_market = _market_view(home_market_raw)
        away_fair, home_fair, reasons = _live_fair_probabilities(game)

        enriched = {
            **game,
            "kalshi_event_ticker": event_ticker,
            "market_connected": bool(event_ticker),
            "away_market": away_market,
            "home_market": home_market,
            "away_fair_pct": round(away_fair * 100, 1),
            "home_fair_pct": round(home_fair * 100, 1),
            "model_version": "MLB-LIVE-v0.1",
        }
        rows.append(enriched)

        away_signal = _signal_for_side(away_code, away_fair, away_market, enriched, reasons)
        home_reasons = [reason for reason in reasons]
        home_signal = _signal_for_side(home_code, home_fair, home_market, enriched, home_reasons)
        if away_signal:
            signals.append(away_signal)
        if home_signal:
            signals.append(home_signal)

    signals.sort(key=lambda item: (item["opportunity_score"], item["edge_pct"]), reverse=True)

    return {
        "sport": "MLB",
        "source": "MLB Stats API + Kalshi",
        "refresh_seconds": 10,
        "market_error": market_error,
        "model": {
            "version": "MLB-LIVE-v0.1",
            "experimental": True,
            "description": "Season-strength baseline adjusted for score, inning/outs remaining, batting side and baserunner state. Requires backtesting/calibration before live-money use.",
        },
        "games": rows,
        "signals": signals,
    }
