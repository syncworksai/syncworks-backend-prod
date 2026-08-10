from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests
from django.db import transaction

from .live_data import TEAM_CODES
from .models import EdgeHistoricalSnapshot
from .research_model import _model_game

KALSHI_BASE = "https://external-api.kalshi.com/trade-api/v2"
MLB_GAME_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _tfs(value: str | None) -> datetime | None:
    if not value or "_" not in value:
        return None
    try:
        day, clock = value.split("_", 1)
        return datetime.strptime(day + clock, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _cents(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


def _get_json(url: str, params: dict[str, Any] | None = None, timeout: int = 15) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _historical_markets_for_date(target_date: date, max_pages: int = 40) -> list[dict[str, Any]]:
    markets: list[dict[str, Any]] = []
    cursor = ""
    target = target_date.isoformat()
    for _ in range(max_pages):
        params: dict[str, Any] = {"series_ticker": "KXMLBGAME", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        payload = _get_json(f"{KALSHI_BASE}/historical/markets", params)
        page = payload.get("markets", [])
        markets.extend(m for m in page if str(m.get("occurrence_datetime", ""))[:10] == target)
        cursor = payload.get("cursor") or ""
        if not cursor or len(page) < 1000:
            break
    return markets


def _game_schedule(target_date: date) -> list[dict[str, Any]]:
    payload = _get_json(
        MLB_SCHEDULE_URL,
        {
            "sportId": 1,
            "date": target_date.isoformat(),
            "hydrate": "team",
        },
    )
    games: list[dict[str, Any]] = []
    for day in payload.get("dates", []):
        games.extend(day.get("games", []))
    return games


def _market_team_code(market: dict[str, Any]) -> str | None:
    ticker = str(market.get("ticker") or "")
    if "-" in ticker:
        return ticker.rsplit("-", 1)[-1].upper()
    subtitle = str(market.get("yes_sub_title") or "").lower()
    for name, code in TEAM_CODES.items():
        if name.lower() in subtitle:
            return code
    return None


def _match_markets(markets: list[dict[str, Any]], away_code: str, home_code: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for market in markets:
        event = str(market.get("event_ticker") or "").upper()
        team_code = _market_team_code(market)
        # KXMLBGAME event tickers encode the participants, but we also require
        # the series and occurrence date from the API metadata before accepting it.
        if event.startswith("KXMLBGAME-") and away_code.upper() in event and home_code.upper() in event:
            if team_code in {away_code.upper(), home_code.upper()}:
                matches.append(market)
    return matches


def _play_states(game_payload: dict[str, Any]) -> tuple[list[datetime], list[dict[str, Any]], datetime | None, datetime | None]:
    game_data = game_payload.get("gameData", {})
    live = game_payload.get("liveData", {})
    plays = (live.get("plays") or {}).get("allPlays") or []
    times: list[datetime] = []
    states: list[dict[str, Any]] = []
    game_start = _dt((game_data.get("datetime") or {}).get("dateTime"))
    game_end = None

    for play in plays:
        about = play.get("about") or {}
        when = _tfs(about.get("endTfs")) or _dt((play.get("playEvents") or [{}])[-1].get("endTime"))
        if not when:
            continue
        result = play.get("result") or {}
        count = play.get("count") or {}
        runners = play.get("runners") or []
        occupied: set[int] = set()
        for runner in runners:
            movement = runner.get("movement") or {}
            details = runner.get("details") or {}
            if details.get("isOut") or movement.get("isOut"):
                continue
            end = movement.get("end")
            try:
                if end in (1, 2, 3):
                    occupied.add(int(end))
            except (TypeError, ValueError):
                pass

        state = {
            "when": when,
            "away_score": int(result.get("awayScore") or 0),
            "home_score": int(result.get("homeScore") or 0),
            "inning": int(about.get("inning") or 0) or None,
            "inning_half": str(about.get("halfInning") or ""),
            "outs": int(count.get("outs") or 0),
            "runners_on_base": len(occupied),
        }
        times.append(when)
        states.append(state)
        game_end = max(game_end, when) if game_end else when

    return times, states, game_start, game_end


def _candles(ticker: str, start_ts: int, end_ts: int) -> list[dict[str, Any]]:
    params = {"start_ts": start_ts, "end_ts": end_ts, "period_interval": 1}
    paths = [
        f"{KALSHI_BASE}/historical/markets/{ticker}/candlesticks",
        f"{KALSHI_BASE}/series/KXMLBGAME/markets/{ticker}/candlesticks",
    ]
    for path in paths:
        try:
            payload = _get_json(path, params)
            return payload.get("candlesticks", [])
        except requests.RequestException:
            continue
    return []


def _candle_price(candle: dict[str, Any], section: str, field: str) -> int | None:
    return _cents(((candle.get(section) or {}).get(field)))


def sync_mlb_kalshi_day(target_date: date, max_games: int = 15, max_minutes_per_game: int = 360) -> dict[str, Any]:
    historical_markets = _historical_markets_for_date(target_date)
    games = _game_schedule(target_date)[:max_games]
    stats = {"date": target_date.isoformat(), "games_seen": len(games), "games_matched": 0, "snapshots_created": 0, "markets_found": len(historical_markets), "errors": []}

    for game in games:
        try:
            away_name = (game.get("teams", {}).get("away", {}).get("team", {}) or {}).get("name")
            home_name = (game.get("teams", {}).get("home", {}).get("team", {}) or {}).get("name")
            away_code = TEAM_CODES.get(away_name)
            home_code = TEAM_CODES.get(home_name)
            game_pk = game.get("gamePk")
            if not away_code or not home_code or not game_pk:
                continue

            matched = _match_markets(historical_markets, away_code, home_code)
            if len(matched) < 2:
                continue

            payload = _get_json(MLB_GAME_URL.format(game_pk=game_pk))
            times, states, game_start, game_end = _play_states(payload)
            if not times:
                continue
            start = game_start or times[0]
            end = min(game_end or times[-1], start + timedelta(minutes=max_minutes_per_game))
            start_ts = int(start.timestamp())
            end_ts = int(end.timestamp())
            state_by_market_time: dict[tuple[str, datetime], dict[str, Any]] = {}

            for market in matched:
                ticker = str(market.get("ticker"))
                side_code = _market_team_code(market)
                if not side_code:
                    continue
                candles = _candles(ticker, start_ts, end_ts)
                if not candles:
                    continue
                for candle in candles:
                    when = datetime.fromtimestamp(int(candle.get("end_period_ts")), tz=timezone.utc)
                    idx = bisect_right(times, when) - 1
                    if idx < 0:
                        continue
                    state = states[idx]
                    state_by_market_time[(ticker, when)] = {"state": state, "side_code": side_code, "market": market, "when": when, "candle": candle}

            if not state_by_market_time:
                continue
            stats["games_matched"] += 1

            rows = []
            for item in state_by_market_time.values():
                state = item["state"]
                market = item["market"]
                candle = item["candle"]
                game_for_model = {
                    "away": {"code": away_code, "score": state["away_score"]},
                    "home": {"code": home_code, "score": state["home_score"]},
                    "inning": state["inning"],
                    "inning_half": state["inning_half"],
                    "outs": state["outs"],
                    "offense": {},
                    "game_state": f"{state['inning_half']} {state['inning']} • {state['outs']} out(s)",
                }
                away_prob, home_prob, _ = _model_game(game_for_model, {away_code: 0.5, home_code: 0.5})
                side_prob = away_prob if item["side_code"] == away_code else home_prob
                rows.append(
                    EdgeHistoricalSnapshot(
                        game_pk=game_pk,
                        market_ticker=market.get("ticker"),
                        event_ticker=market.get("event_ticker") or "",
                        observed_at=item["when"],
                        away_code=away_code,
                        home_code=home_code,
                        side_code=item["side_code"],
                        away_score=state["away_score"],
                        home_score=state["home_score"],
                        inning=state["inning"],
                        inning_half=state["inning_half"],
                        outs=state["outs"],
                        runners_on_base=state["runners_on_base"],
                        yes_bid_cents=_candle_price(candle, "yes_bid", "close_dollars"),
                        yes_ask_cents=_candle_price(candle, "yes_ask", "close_dollars"),
                        yes_close_cents=_cents(((candle.get("price") or {}).get("close_dollars"))),
                        market_result=str(market.get("result") or ""),
                        model_probability_bps=int(round(side_prob * 10000)),
                    )
                )
            with transaction.atomic():
                for row in rows:
                    _, created = EdgeHistoricalSnapshot.objects.update_or_create(
                        market_ticker=row.market_ticker,
                        observed_at=row.observed_at,
                        defaults={field.name: getattr(row, field.name) for field in row._meta.fields if field.name not in {"id", "market_ticker", "observed_at", "created_at"}},
                    )
                    if created:
                        stats["snapshots_created"] += 1
        except Exception as exc:  # sync should report a bad game without killing the whole day
            stats["errors"].append({"game_pk": game.get("gamePk"), "error": str(exc)})

    return stats


def summarize_replay(target_date: date, minimum_edge_pct: float = 8.0) -> dict[str, Any]:
    rows = list(EdgeHistoricalSnapshot.objects.filter(observed_at__date=target_date).values())
    eligible = []
    for row in rows:
        ask = row.get("yes_ask_cents") or row.get("yes_close_cents")
        model = (row.get("model_probability_bps") or 0) / 100
        if not ask:
            continue
        edge = model - ask
        if edge >= minimum_edge_pct:
            won = row.get("market_result") == "yes"
            eligible.append({"row": row, "edge_pct": edge, "won": won})

    wins = sum(1 for item in eligible if item["won"])
    losses = len(eligible) - wins
    brier = None
    if rows:
        scores = []
        for row in rows:
            if row.get("market_result") not in {"yes", "no"} or row.get("model_probability_bps") is None:
                continue
            p = row["model_probability_bps"] / 10000
            y = 1.0 if row["market_result"] == "yes" else 0.0
            scores.append((p - y) ** 2)
        if scores:
            brier = round(sum(scores) / len(scores), 6)

    by_state: dict[str, dict[str, Any]] = {}
    for item in eligible:
        row = item["row"]
        deficit = abs(int(row["away_score"]) - int(row["home_score"]))
        trailing = row["side_code"] == row["away_code"] and row["away_score"] < row["home_score"] or row["side_code"] == row["home_code"] and row["home_score"] < row["away_score"]
        if not trailing:
            continue
        key = f"down_{deficit}_inning_{row['inning']}"
        bucket = by_state.setdefault(key, {"samples": 0, "wins": 0})
        bucket["samples"] += 1
        bucket["wins"] += int(item["won"])

    for bucket in by_state.values():
        bucket["win_rate_pct"] = round(bucket["wins"] / bucket["samples"] * 100, 2) if bucket["samples"] else 0

    return {
        "date": target_date.isoformat(),
        "snapshot_count": len(rows),
        "eligible_count": len(eligible),
        "wins": wins,
        "losses": losses,
        "observed_win_rate_pct": round(wins / len(eligible) * 100, 2) if eligible else None,
        "brier_score": brier,
        "minimum_edge_pct": minimum_edge_pct,
        "state_buckets": by_state,
        "note": "Historical replay uses one-minute Kalshi candlesticks matched to the latest MLB play state at or before each candle. It is research data, not proof of profitability.",
    }
