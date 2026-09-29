from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import Any

import requests

KALSHI_MARKETS_URL = "https://external-api.kalshi.com/trade-api/v2/markets"
ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/{league}/scoreboard"
SPORTS = {
    "NFL": {"league": "nfl", "series": "KXNFLGAME", "refresh": 30, "limit": 100},
    "NCAAF": {"league": "college-football", "series": "KXNCAAFGAME", "refresh": 60, "limit": 400},
}
NFL_CODES = {"WSH": "WAS", "LAR": "LA"}


def _cents(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


def _american_probability(value: Any) -> float | None:
    try:
        odds = float(value)
    except (TypeError, ValueError):
        return None
    if odds == 0:
        return None
    return (-odds) / ((-odds) + 100.0) if odds < 0 else 100.0 / (odds + 100.0)


def _no_vig_pair(away_ml: Any, home_ml: Any) -> tuple[float | None, float | None]:
    away, home = _american_probability(away_ml), _american_probability(home_ml)
    if away is None or home is None or away + home <= 0:
        return None, None
    total = away + home
    return away / total, home / total


def _norm(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _team(raw: dict[str, Any], sport: str) -> dict[str, Any]:
    team = raw.get("team") or {}
    code = str(team.get("abbreviation") or "").upper()
    records = raw.get("records") or []
    return {
        "name": team.get("displayName") or team.get("shortDisplayName") or code,
        "short_name": team.get("shortDisplayName") or team.get("name") or code,
        "location": team.get("location"),
        "code": code,
        "market_code": NFL_CODES.get(code, code) if sport == "NFL" else code,
        "score": int(float(raw.get("score") or 0)),
        "record": records[0].get("summary") if records else None,
    }


def _aliases(team: dict[str, Any]) -> list[str]:
    values = [team.get("market_code"), team.get("code"), team.get("name"), team.get("short_name"), team.get("location")]
    out = []
    for value in values:
        alias = _norm(value)
        if len(alias) >= 3 and alias not in out:
            out.append(alias)
    return out


def _market_blob(market: dict[str, Any]) -> str:
    return _norm(" ".join(str(market.get(key) or "") for key in (
        "ticker", "event_ticker", "title", "subtitle", "yes_sub_title", "no_sub_title"
    )))


def _alias_score(blob: str, aliases: list[str]) -> int:
    score = 0
    for alias in aliases:
        if alias and alias in blob:
            score = max(score, 4 if len(alias) >= 6 else 2)
    return score


def _match_event(by_event: dict[str, list[dict[str, Any]]], away: dict[str, Any], home: dict[str, Any]) -> str | None:
    away_aliases, home_aliases = _aliases(away), _aliases(home)
    away_code, home_code = _norm(away.get("market_code")), _norm(home.get("market_code"))
    best, best_score = None, 0
    for event_ticker, markets in by_event.items():
        blob = "".join(_market_blob(m) for m in markets)
        score = _alias_score(blob, away_aliases) + _alias_score(blob, home_aliases)
        ticker = _norm(event_ticker)
        if away_code and home_code and away_code in ticker and home_code in ticker:
            score += 8
        if score > best_score:
            best, best_score = event_ticker, score
    return best if best_score >= 6 else None


def _market_for_team(markets: list[dict[str, Any]], team: dict[str, Any]) -> dict[str, Any] | None:
    code, aliases = _norm(team.get("market_code")), _aliases(team)
    best, best_score = None, 0
    for market in markets:
        score = _alias_score(_market_blob(market), aliases)
        if code and _norm(market.get("ticker")).endswith(code):
            score += 8
        if score > best_score:
            best, best_score = market, score
    return best if best_score >= 4 else None


def _market_view(market: dict[str, Any] | None) -> dict[str, Any] | None:
    if not market:
        return None
    return {
        "ticker": market.get("ticker"),
        "yes_bid_cents": _cents(market.get("yes_bid_dollars")),
        "yes_ask_cents": _cents(market.get("yes_ask_dollars")),
        "last_price_cents": _cents(market.get("last_price_dollars")),
        "volume": market.get("volume_fp"),
        "liquidity_dollars": market.get("liquidity_dollars"),
        "status": market.get("status"),
    }


def _kalshi_markets(series: str) -> list[dict[str, Any]]:
    response = requests.get(KALSHI_MARKETS_URL, params={
        "series_ticker": series, "status": "open", "limit": 1000, "mve_filter": "exclude",
    }, timeout=8)
    response.raise_for_status()
    return response.json().get("markets", [])


def _espn_games(sport: str, target_date: str | None = None) -> list[dict[str, Any]]:
    config = SPORTS[sport]
    if target_date:
        dates = target_date.replace("-", "")
    else:
        start = date.today()
        dates = f"{start:%Y%m%d}-{start + timedelta(days=7):%Y%m%d}"
    response = requests.get(
        ESPN_SCOREBOARD_URL.format(league=config["league"]),
        params={"dates": dates, "limit": config["limit"]},
        timeout=8,
    )
    response.raise_for_status()
    games = []
    for event in response.json().get("events", []):
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        comp = competitions[0]
        competitors = comp.get("competitors") or []
        away_raw = next((c for c in competitors if c.get("homeAway") == "away"), None)
        home_raw = next((c for c in competitors if c.get("homeAway") == "home"), None)
        if not away_raw or not home_raw:
            continue
        away, home = _team(away_raw, sport), _team(home_raw, sport)
        status = event.get("status") or comp.get("status") or {}
        status_type = status.get("type") or {}
        odds = (comp.get("odds") or [{}])[0]
        away_ml = (odds.get("awayTeamOdds") or {}).get("moneyLine")
        home_ml = (odds.get("homeTeamOdds") or {}).get("moneyLine")
        away_fair, home_fair = _no_vig_pair(away_ml, home_ml)
        games.append({
            "game_pk": event.get("id"), "game_date": event.get("date"),
            "status": status_type.get("description") or status_type.get("name") or "Scheduled",
            "is_live": status_type.get("state") == "in", "completed": bool(status_type.get("completed")),
            "away": away, "home": home,
            "game_state": status_type.get("shortDetail") or status_type.get("detail") or "Scheduled",
            "period": status.get("period"), "clock": status.get("displayClock"),
            "odds": {
                "provider": (odds.get("provider") or {}).get("name"), "details": odds.get("details"),
                "spread": odds.get("spread"), "over_under": odds.get("overUnder"),
                "away_moneyline": away_ml, "home_moneyline": home_ml,
                "away_fair_probability": away_fair, "home_fair_probability": home_fair,
            },
        })
    return sorted(games, key=lambda row: row.get("game_date") or "")


def _fee_cents(contracts: int, price_cents: int) -> int:
    if contracts <= 0 or not 0 < price_cents < 100:
        return 0
    p = price_cents / 100.0
    return int(math.ceil((0.07 * contracts * p * (1.0 - p) * 100.0) - 1e-9))


def _stake_plan(price_cents: int, edge_pct: float, minimum_edge: float) -> dict[str, Any]:
    primary = 25 <= price_cents <= 45
    target = 0 if edge_pct < minimum_edge else (750 if primary and edge_pct >= max(10.0, minimum_edge + 2.0) else 500)
    contracts = 0
    if target:
        for candidate in range(1, 1000):
            if candidate * price_cents + _fee_cents(candidate, price_cents) > target:
                break
            contracts = candidate
    fee = _fee_cents(contracts, price_cents)
    cost, payout = contracts * price_cents + fee, contracts * 100
    return {
        "pool_dollars": 100, "participants": 4, "primary_price_band": primary,
        "target_stake_cents": target, "contracts": contracts, "estimated_entry_fee_cents": fee,
        "estimated_cost_cents": cost, "gross_payout_cents": payout,
        "profit_if_correct_cents": payout - cost,
        "per_person_cost_cents": int(round(cost / 4.0)) if cost else 0,
        "per_person_payout_cents": int(round(payout / 4.0)) if payout else 0,
        "fee_note": "Estimated with Kalshi's standard taker formula; market-specific fees can differ.",
    }


def _signal(sport: str, game: dict[str, Any], team: dict[str, Any], fair: float | None, moneyline: Any,
            market: dict[str, Any] | None, minimum_edge: float) -> dict[str, Any] | None:
    if not market or fair is None:
        return None
    ask = market.get("yes_ask_cents")
    if ask is None or not 0 < ask < 100:
        return None
    fair_pct, edge = round(fair * 100.0, 1), round((fair * 100.0) - ask, 1)
    yellow = max(3.0, min(6.0, minimum_edge / 2.0))
    signal = "GREEN" if edge >= minimum_edge else ("YELLOW" if edge >= yellow else "RED")
    primary = 25 <= ask <= 45
    score = max(0, min(100, int(round(45 + edge * 4 + (10 if primary else 0)))))
    reasons = [
        f"Consensus no-vig win probability: {fair_pct:.1f}%",
        f"Kalshi ask: {ask}¢; modeled gap: {edge:+.1f} points",
    ]
    provider = game.get("odds", {}).get("provider")
    if provider:
        reasons.append(f"Reference odds provider: {provider}")
    if moneyline not in (None, ""):
        reasons.append(f"Reference moneyline: {moneyline}")
    reasons.append("Inside the 25–45¢ primary value band." if primary else "Outside the 25–45¢ primary value band.")
    ticker = market.get("ticker")
    return {
        "id": ticker or f"{sport}-{game.get('game_pk')}-{team.get('code')}",
        "sport": sport, "event_key": str(game.get("game_pk")),
        "matchup": f"{game['away'].get('code')} @ {game['home'].get('code')}",
        "game_state": game.get("game_state") or game.get("status"),
        "side": f"{team.get('code')} YES", "team_code": team.get("code"),
        "market_ticker": ticker, "market_price_cents": int(ask), "market_bid_cents": market.get("yes_bid_cents"),
        "model_probability_pct": fair_pct, "edge_pct": edge, "opportunity_score": score, "signal": signal,
        "research_status": "PRICE BELOW NO-VIG CONSENSUS" if signal == "GREEN" else "RESEARCH",
        "model_version": f"EDGE-{sport}-NO-VIG-v1", "model_source": "Pregame no-vig moneyline consensus",
        "max_entry_cents": max(1, min(99, int(math.floor(fair_pct - minimum_edge)))),
        "primary_price_band": primary, "stake_plan": _stake_plan(int(ask), edge, minimum_edge),
        "why": reasons, "observed_at": date.today().isoformat(),
    }


def get_football_board(sport: str, target_date: str | None = None, minimum_edge: float = 5.0) -> dict[str, Any]:
    sport = sport.upper()
    if sport not in SPORTS:
        raise ValueError("Unsupported football sport.")
    config = SPORTS[sport]
    games = _espn_games(sport, target_date)
    try:
        markets, market_error = _kalshi_markets(config["series"]), None
    except requests.RequestException as exc:
        markets, market_error = [], str(exc)
    by_event: dict[str, list[dict[str, Any]]] = {}
    for market in markets:
        event_ticker = str(market.get("event_ticker") or "")
        if event_ticker:
            by_event.setdefault(event_ticker, []).append(market)

    rows, signals = [], []
    for game in games:
        event_ticker = _match_event(by_event, game["away"], game["home"])
        event_markets = by_event.get(event_ticker, []) if event_ticker else []
        away_market = _market_view(_market_for_team(event_markets, game["away"]))
        home_market = _market_view(_market_for_team(event_markets, game["home"]))
        row = {**game, "kalshi_event_ticker": event_ticker, "market_connected": bool(event_ticker),
               "away_market": away_market, "home_market": home_market}
        rows.append(row)
        odds = row.get("odds", {})
        for item in (
            _signal(sport, row, row["away"], odds.get("away_fair_probability"), odds.get("away_moneyline"), away_market, minimum_edge),
            _signal(sport, row, row["home"], odds.get("home_fair_probability"), odds.get("home_moneyline"), home_market, minimum_edge),
        ):
            if item:
                signals.append(item)

    signals.sort(key=lambda item: (
        1 if item["signal"] == "GREEN" else 0,
        1 if item.get("primary_price_band") else 0,
        item.get("edge_pct", 0), item.get("opportunity_score", 0),
    ), reverse=True)
    return {
        "sport": sport, "source": "ESPN pregame odds + Kalshi", "refresh_seconds": config["refresh"],
        "market_error": market_error, "games": rows, "signals": signals,
        "strategy": {
            "pool_dollars": 100, "participants": 4, "contribution_per_person_dollars": 25,
            "primary_price_band_cents": [25, 45], "standard_stake_dollars": 5,
            "strong_edge_stake_dollars": 7.5, "minimum_edge_pct": minimum_edge,
            "method": "Compare Kalshi ask with a no-vig pregame moneyline probability; skip games without reference odds.",
            "risk_note": "Research/paper signal only. Price gaps can disappear before execution and do not guarantee profit.",
        },
        "model": {
            "version": f"EDGE-{sport}-NO-VIG-v1", "status": "research_only",
            "minimum_edge_pct": minimum_edge, "calibrated": False,
            "note": "Market-derived no-vig reference probability, not a guaranteed true probability.",
        },
    }
