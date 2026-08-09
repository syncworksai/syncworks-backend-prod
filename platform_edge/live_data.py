from __future__ import annotations

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
                    },
                    "home": {
                        "name": home_name,
                        "code": TEAM_CODES.get(home_name, home.get("team", {}).get("abbreviation")),
                        "score": home.get("score", 0),
                        "probable_pitcher": home.get("probablePitcher", {}).get("fullName"),
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

    for game in games:
        away_code = game["away"].get("code")
        home_code = game["home"].get("code")
        event_ticker = _same_game_event(markets, away_code, home_code)
        away_market = index.get((event_ticker, str(away_code).upper())) if event_ticker and away_code else None
        home_market = index.get((event_ticker, str(home_code).upper())) if event_ticker and home_code else None
        rows.append(
            {
                **game,
                "kalshi_event_ticker": event_ticker,
                "market_connected": bool(event_ticker),
                "away_market": _market_view(away_market),
                "home_market": _market_view(home_market),
            }
        )

    return {
        "sport": "MLB",
        "source": "MLB Stats API + Kalshi",
        "refresh_seconds": 10,
        "market_error": market_error,
        "games": rows,
    }
