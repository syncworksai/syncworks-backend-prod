from __future__ import annotations

import os
from datetime import datetime, timezone

import edge_v08b_reversion as observation_source
import edge_v10_strategy_discovery as discovery
from edge_v07_pregame_holdout import KALSHI, dt, get_json, markets_for_day as live_markets_for_day

_HISTORICAL_MLB_MARKETS = None


def historical_mlb_markets():
    global _HISTORICAL_MLB_MARKETS
    if _HISTORICAL_MLB_MARKETS is not None:
        return _HISTORICAL_MLB_MARKETS
    rows = []
    cursor = ""
    for _ in range(20):
        params = {"series_ticker": "KXMLBGAME", "limit": 1000, "mve_filter": "exclude"}
        if cursor:
            params["cursor"] = cursor
        payload = get_json(f"{KALSHI}/historical/markets", params)
        rows.extend(payload.get("markets", []))
        cursor = payload.get("cursor") or ""
        if not cursor:
            break
    _HISTORICAL_MLB_MARKETS = rows
    return rows


def combined_markets_for_day(day):
    # Recent settled markets remain in /markets. Archived markets must be sourced from
    # /historical/markets. Historical market listing has no settled-time query filter,
    # so fetch the KXMLBGAME archive once and filter locally by settlement timestamp.
    recent = live_markets_for_day(day)
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).timestamp()
    end = start + 172800
    historical = []
    for market in historical_mlb_markets():
        settled = dt(market.get("settlement_ts") or market.get("close_time") or market.get("expiration_time"))
        if settled and start <= settled.timestamp() <= end:
            historical.append(market)
    deduped = {}
    for market in recent + historical:
        ticker = market.get("ticker")
        if ticker:
            deduped[ticker] = market
    return list(deduped.values())


if __name__ == "__main__":
    observation_source.markets_for_day = combined_markets_for_day
    discovery.run(int(os.environ.get("EDGE_DAYS", "120")))
