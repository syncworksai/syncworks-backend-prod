from __future__ import annotations

import json
import os
from itertools import product
from pathlib import Path

import edge_v10_strategy_discovery as discovery
import edge_v08b_reversion as observation_source
from edge_v07_pregame_holdout import KALSHI, dt, get_json, markets_for_day as live_markets_for_day
from datetime import datetime, timezone

_HISTORICAL_MLB_MARKETS = None


def historical_mlb_markets():
    global _HISTORICAL_MLB_MARKETS
    if _HISTORICAL_MLB_MARKETS is not None:
        return _HISTORICAL_MLB_MARKETS
    rows = []
    cursor = ""
    for _ in range(20):
        params = {"series_ticker": "KXMLBGAME", "limit": 1000}
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


def build_strategy_b_rules():
    # Strategy B is intentionally separated from Strategy A's 55-65% pregame band.
    # We search two independent regimes: underdogs/coin-flips and stronger favorites.
    strengths = [
        (30, 40), (35, 45), (40, 50), (45, 55),
        (65, 70), (65, 75), (70, 80), (75, 90),
    ]
    deficits = [(1,), (2,), (1, 2), (2, 3)]
    innings = [(2, 4), (3, 5), (4, 6), (5, 7)]
    drops = [10, 15, 20, 25]
    edges = [3, 5, 8, 10]
    batting = [None, True, False]
    rules = []
    for pre, de, inn, drop, edge, bat in product(strengths, deficits, innings, drops, edges, batting):
        rules.append({
            "pregame": pre,
            "deficits": de,
            "innings": inn,
            "drop_min": drop,
            "edge_min": edge,
            "batting": bat,
        })
    return rules


def run(days=120):
    observation_source.markets_for_day = combined_markets_for_day
    discovery.corrected_build_observations = observation_source.corrected_build_observations
    discovery.build_rules = build_strategy_b_rules
    discovery.run(days)

    src = Path("edge_v10_results.json")
    if not src.exists():
        raise RuntimeError("Strategy B discovery did not produce results")
    result = json.loads(src.read_text())
    result["version"] = "EDGE-MLB-v1.1-strategy-b-discovery"
    result["search"]["independence_constraint"] = "Excludes Strategy A pregame band 55-65%; separate candidate family only"
    result["strategy_a_frozen"] = True
    result["strategy_a_modified"] = False
    Path("edge_v11_strategy_b_results.json").write_text(json.dumps(result, indent=2))

    holdout = Path("edge_v10_final_holdout_replays.json")
    if holdout.exists():
        Path("edge_v11_strategy_b_holdout_replays.json").write_text(holdout.read_text())

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run(int(os.environ.get("EDGE_DAYS", "120")))
