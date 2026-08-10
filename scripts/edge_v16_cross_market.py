from __future__ import annotations

import json
import math
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path

import requests

KALSHI = "https://external-api.kalshi.com/trade-api/v2"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "SyncWorks-EDGE-cross-market/1.6"})
ENTRY_FRICTION = 1.0
EXIT_FRICTION = 0.5


def get_json(url, params=None, timeout=30):
    r = SESSION.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def parse_dt(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def cents(v):
    if v in (None, ""):
        return None
    try:
        x = float(v)
        return int(round(x * 100)) if x <= 1.5 else int(round(x))
    except Exception:
        return None


def candle_price(c, key):
    sec = c.get(key) or {}
    raw = sec.get("close_dollars") if "close_dollars" in sec else sec.get("close")
    return cents(raw)


def series_list():
    rows = []
    cursor = ""
    for _ in range(10):
        params = {"category": "Sports", "include_volume": "true", "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        payload = get_json(f"{KALSHI}/series", params)
        rows.extend(payload.get("series", []))
        cursor = payload.get("cursor") or ""
        if not cursor:
            break
    return rows


def classify_series(s):
    text = " ".join([
        str(s.get("title") or ""),
        str(s.get("ticker") or ""),
        " ".join(str(x) for x in (s.get("tags") or [])),
    ]).lower()
    if any(k in text for k in ("tennis", "atp", "wta")):
        return "TENNIS"
    if any(k in text for k in ("nba", "wnba", "basketball")):
        return "BASKETBALL"
    if any(k in text for k in ("nfl", "football", "ncaa football", "college football")):
        return "FOOTBALL"
    return None


def volume_value(s):
    for key in ("volume_fp", "volume", "dollar_volume"):
        try:
            return float(s.get(key) or 0)
        except Exception:
            pass
    return 0.0


def markets_for_series(series_ticker):
    dedupe = {}
    # Recent settled markets.
    cursor = ""
    for _ in range(5):
        params = {"series_ticker": series_ticker, "status": "settled", "limit": 1000, "mve_filter": "exclude"}
        if cursor:
            params["cursor"] = cursor
        try:
            payload = get_json(f"{KALSHI}/markets", params)
        except Exception:
            break
        for m in payload.get("markets", []):
            if m.get("ticker"):
                dedupe[m["ticker"]] = m
        cursor = payload.get("cursor") or ""
        if not cursor:
            break
    # Archived markets. Historical API only allows its own filter set.
    cursor = ""
    for _ in range(10):
        params = {"series_ticker": series_ticker, "limit": 1000}
        if cursor:
            params["cursor"] = cursor
        try:
            payload = get_json(f"{KALSHI}/historical/markets", params)
        except Exception:
            break
        for m in payload.get("markets", []):
            if m.get("ticker"):
                dedupe[m["ticker"]] = m
        cursor = payload.get("cursor") or ""
        if not cursor:
            break
    return list(dedupe.values())


def clean_two_sided_events(markets, cutoff):
    by_event = defaultdict(list)
    for m in markets:
        result = str(m.get("result") or "").lower()
        if result not in {"yes", "no"}:
            continue
        close = parse_dt(m.get("close_time") or m.get("settlement_ts") or m.get("expiration_time") or m.get("latest_expiration_time"))
        if not close or close < cutoff:
            continue
        event = str(m.get("event_ticker") or "")
        if event:
            by_event[event].append(m)
    out = []
    for event, ms in by_event.items():
        if len(ms) != 2:
            continue
        results = sorted(str(m.get("result") or "").lower() for m in ms)
        if results != ["no", "yes"]:
            continue
        out.append((event, ms))
    return out


def fetch_candles(series_ticker, market, start_ts, end_ts):
    ticker = market["ticker"]
    urls = [
        f"{KALSHI}/series/{series_ticker}/markets/{ticker}/candlesticks",
        f"{KALSHI}/historical/markets/{ticker}/candlesticks",
    ]
    for url in urls:
        try:
            p = get_json(url, {"start_ts": int(start_ts), "end_ts": int(end_ts), "period_interval": 1})
            rows = p.get("candlesticks", [])
            if rows:
                return rows
        except Exception:
            pass
    return []


def build_event_record(bucket, series, event, markets):
    close_times = [parse_dt(m.get("close_time") or m.get("settlement_ts") or m.get("expiration_time") or m.get("latest_expiration_time")) for m in markets]
    close_times = [x for x in close_times if x]
    if not close_times:
        return None
    close = max(close_times)
    # Price-only discovery window: intentionally broad enough to include the full live event for tennis/basketball/football.
    hours = 8 if bucket == "TENNIS" else (6 if bucket == "BASKETBALL" else 7)
    start = close - timedelta(hours=hours)
    histories = {}
    for m in markets:
        histories[m["ticker"]] = fetch_candles(series["ticker"], m, start.timestamp(), (close + timedelta(minutes=10)).timestamp())
    if any(len(histories[m["ticker"]]) < 10 for m in markets):
        return None

    by_side = {}
    for m in markets:
        rows = []
        for c in histories[m["ticker"]]:
            ts = int(c.get("end_period_ts") or 0)
            ask = candle_price(c, "yes_ask")
            bid = candle_price(c, "yes_bid")
            if ask is None or not 1 <= ask <= 99:
                continue
            if bid is None or not 0 <= bid <= 99:
                bid = max(0, ask - 2)
            if start.timestamp() <= ts <= close.timestamp() + 600:
                rows.append({"ts": ts, "ask": ask, "bid": bid})
        rows.sort(key=lambda x: x["ts"])
        if len(rows) < 10:
            return None
        by_side[m["ticker"]] = {"market": m, "rows": rows}

    # Find earliest time where both markets have a contemporaneous quote within five minutes.
    a, b = markets
    ar, br = by_side[a["ticker"]]["rows"], by_side[b["ticker"]]["rows"]
    best = None
    j = 0
    for x in ar:
        while j + 1 < len(br) and br[j + 1]["ts"] <= x["ts"]:
            j += 1
        candidates = [br[j]]
        if j + 1 < len(br):
            candidates.append(br[j + 1])
        y = min(candidates, key=lambda q: abs(q["ts"] - x["ts"]))
        if abs(y["ts"] - x["ts"]) <= 300:
            best = (x, y)
            break
    if not best:
        return None
    a0, b0 = best
    total = a0["ask"] + b0["ask"]
    if total <= 0:
        return None
    pa = 100 * a0["ask"] / total
    pb = 100 - pa
    favorite = a if pa >= pb else b
    dog = b if favorite is a else a
    fav_pre = max(pa, pb)
    if not 50 <= fav_pre <= 80:
        return None

    return {
        "bucket": bucket,
        "series_ticker": series["ticker"],
        "series_title": series.get("title"),
        "event_ticker": event,
        "close_ts": int(close.timestamp()),
        "baseline_ts": max(a0["ts"], b0["ts"]),
        "favorite_ticker": favorite["ticker"],
        "dog_ticker": dog["ticker"],
        "favorite_pregame": round(fav_pre, 2),
        "favorite_won": str(favorite.get("result") or "").lower() == "yes",
        "dog_won": str(dog.get("result") or "").lower() == "yes",
        "favorite_rows": by_side[favorite["ticker"]]["rows"],
        "dog_rows": by_side[dog["ticker"]]["rows"],
    }


def quote_at(rows, ts):
    prior = [r for r in rows if r["ts"] <= ts]
    if prior:
        return prior[-1]
    return rows[0] if rows else None


def replay(event, cfg):
    frows = [r for r in event["favorite_rows"] if r["ts"] >= event["baseline_ts"]]
    drows = [r for r in event["dog_rows"] if r["ts"] >= event["baseline_ts"]]
    if not frows or not drows:
        return None
    remaining_sec = cfg["min_remaining_minutes"] * 60
    trigger = None
    dog_at = None
    for fr in frows:
        if fr["ts"] > event["close_ts"] - remaining_sec:
            break
        if fr["ask"] >= cfg["trigger"]:
            q = quote_at(drows, fr["ts"])
            if q and abs(q["ts"] - fr["ts"]) <= 300:
                trigger, dog_at = fr, q
                break
    if not trigger:
        return None

    # One unit favorite position from baseline, plus dynamic opposite-side hedge at trigger.
    fav0 = quote_at(frows, event["baseline_ts"])
    if not fav0:
        return None
    fav_entry = min(99.0, float(fav0["ask"]) + ENTRY_FRICTION)
    fav_contracts = 100.0 / fav_entry
    hedge_cost = cfg["hedge_mult"]
    dog_entry = min(99.0, float(dog_at["ask"]) + ENTRY_FRICTION)
    dog_contracts = hedge_cost * 100.0 / dog_entry

    dog_value = None
    hedge_closed = False
    hedge_exit_ts = None
    target_px = dog_entry + cfg["target"]
    for q in drows:
        if q["ts"] <= dog_at["ts"]:
            continue
        executable_bid = max(0.0, float(q["bid"]) - EXIT_FRICTION)
        if executable_bid >= target_px:
            dog_value = dog_contracts * executable_bid / 100.0
            hedge_closed = True
            hedge_exit_ts = q["ts"]
            break
    if dog_value is None:
        dog_value = dog_contracts if event["dog_won"] else 0.0
    fav_value = fav_contracts if event["favorite_won"] else 0.0
    cost = 1.0 + hedge_cost
    pnl = fav_value + dog_value - cost
    return {
        "bucket": event["bucket"],
        "event_ticker": event["event_ticker"],
        "close_ts": event["close_ts"],
        "favorite_pregame": event["favorite_pregame"],
        "trigger_price": trigger["ask"],
        "dog_entry": round(dog_entry, 2),
        "hedge_closed_early": hedge_closed,
        "hedge_exit_ts": hedge_exit_ts,
        "cost": round(cost, 4),
        "pnl": round(pnl, 4),
        "roi_pct": round(100 * pnl / cost, 2),
    }


def stats(rows):
    if not rows:
        return {"events": 0, "roi_pct": None}
    cost = sum(r["cost"] for r in rows)
    pnl = sum(r["pnl"] for r in rows)
    equity = peak = drawdown = 0.0
    for r in sorted(rows, key=lambda x: x["close_ts"]):
        equity += r["pnl"]
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return {
        "events": len(rows),
        "roi_pct": round(100 * pnl / cost, 2),
        "total_pnl_units": round(pnl, 3),
        "positive_event_pct": round(100 * sum(r["pnl"] > 0 for r in rows) / len(rows), 2),
        "avg_event_roi_pct": round(sum(r["roi_pct"] for r in rows) / len(rows), 2),
        "max_drawdown_units": round(drawdown, 3),
        "hedge_early_exit_pct": round(100 * sum(r["hedge_closed_early"] for r in rows) / len(rows), 2),
    }


def configs():
    out = []
    for trigger, mult, target, remain, band in product(
        [75, 80, 85, 90],
        [.10, .15, .20, .25, .30],
        [3, 5, 7, 10],
        [30, 60, 90, 120],
        [(50,55),(55,60),(60,65),(65,70),(70,80),(50,80)],
    ):
        out.append({
            "trigger": trigger,
            "hedge_mult": mult,
            "target": target,
            "min_remaining_minutes": remain,
            "pregame_min": band[0],
            "pregame_max": band[1],
        })
    return out


def split_events(events):
    events = sorted(events, key=lambda e: e["close_ts"])
    n = len(events)
    c1 = max(1, int(n * .50))
    c2 = max(c1 + 1, int(n * .75))
    return events[:c1], events[c1:c2], events[c2:]


def evaluate(events, cfg):
    selected = [e for e in events if cfg["pregame_min"] <= e["favorite_pregame"] < cfg["pregame_max"]]
    reps = [replay(e, cfg) for e in selected]
    return [r for r in reps if r]


def discover(bucket, events):
    dev, val, hold = split_events(events)
    viable = []
    for cfg in configs():
        dr, vr = evaluate(dev, cfg), evaluate(val, cfg)
        ds, vs = stats(dr), stats(vr)
        if ds["events"] < 12 or vs["events"] < 6:
            continue
        if ds["roi_pct"] is None or vs["roi_pct"] is None or min(ds["roi_pct"], vs["roi_pct"]) <= 0:
            continue
        score = min(ds["roi_pct"], vs["roi_pct"]) + .15 * (ds["roi_pct"] + vs["roi_pct"]) / 2
        viable.append((score, cfg, ds, vs))
    viable.sort(key=lambda x: (x[0], x[3]["events"]), reverse=True)
    winner = viable[0] if viable else None
    hold_rows = evaluate(hold, winner[1]) if winner else []
    return {
        "bucket": bucket,
        "events_total": len(events),
        "split_counts": {"development": len(dev), "validation": len(val), "holdout": len(hold)},
        "configs_tested": len(configs()),
        "robust_positive_candidates": len(viable),
        "selected": {
            "config": winner[1],
            "development": winner[2],
            "validation": winner[3],
            "holdout": stats(hold_rows),
        } if winner else None,
        "top_candidates_pre_holdout": [
            {"score": round(x[0], 3), "config": x[1], "development": x[2], "validation": x[3]}
            for x in viable[:10]
        ],
    }


def run(days=180, max_events_per_bucket=220):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_series = series_list()
    selected_series = defaultdict(list)
    for s in all_series:
        bucket = classify_series(s)
        if bucket in {"TENNIS", "BASKETBALL", "FOOTBALL"}:
            selected_series[bucket].append(s)
    for bucket in selected_series:
        selected_series[bucket].sort(key=volume_value, reverse=True)
        selected_series[bucket] = selected_series[bucket][:8]

    coverage = {"series_discovered": {k: len(v) for k,v in selected_series.items()}, "series_used": {}, "events_scanned": {}, "events_usable": {}, "errors": []}
    records = defaultdict(list)
    for bucket in ("TENNIS", "BASKETBALL", "FOOTBALL"):
        coverage["series_used"][bucket] = []
        candidates = []
        for s in selected_series.get(bucket, []):
            try:
                ms = markets_for_series(s["ticker"])
                evs = clean_two_sided_events(ms, cutoff)
                candidates.extend((s, event, pair) for event, pair in evs)
                coverage["series_used"][bucket].append({"ticker": s["ticker"], "title": s.get("title"), "events": len(evs)})
            except Exception as exc:
                coverage["errors"].append({"series": s.get("ticker"), "error": str(exc)})
        candidates.sort(key=lambda x: max((parse_dt(m.get("close_time") or m.get("settlement_ts") or m.get("expiration_time") or m.get("latest_expiration_time")) or cutoff for m in x[2])), reverse=True)
        candidates = candidates[:max_events_per_bucket]
        coverage["events_scanned"][bucket] = len(candidates)
        for i, (s, event, pair) in enumerate(candidates):
            try:
                rec = build_event_record(bucket, s, event, pair)
                if rec:
                    records[bucket].append(rec)
            except Exception as exc:
                coverage["errors"].append({"event": event, "error": str(exc)})
            if i % 20 == 0:
                time.sleep(.1)
        coverage["events_usable"][bucket] = len(records[bucket])

    results = {bucket: discover(bucket, records[bucket]) for bucket in ("TENNIS", "BASKETBALL", "FOOTBALL") if records[bucket]}
    result = {
        "version": "EDGE-v1.6-cross-market-volatility",
        "period_days": days,
        "method": "Price-only E-style volatility discovery on clean two-sided settled winner events; 50% development / 25% validation / 25% untouched holdout.",
        "coverage": coverage,
        "results": results,
        "guardrails": [
            "This does not assume MLB thresholds transfer across sports; each bucket selects its own rule before holdout.",
            "Only clean two-sided settled winner events are used; props, spreads and outrights are excluded.",
            "Uses observed one-minute bid/ask history with +1c entry and -0.5c exit friction.",
            "Price-only discovery is a first pass; any surviving sport must later be enriched with sport-specific live state before production use.",
            "Historical simulation is not proof of future profitability and no live-money path is enabled.",
        ],
    }
    Path("edge_v16_cross_market_results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run(int(os.environ.get("EDGE_DAYS", "180")), int(os.environ.get("EDGE_MAX_EVENTS", "220")))
