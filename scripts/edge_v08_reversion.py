from __future__ import annotations

import bisect
import json
import math
import os
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from edge_v07_pregame_holdout import (
    candle_ask,
    candles,
    cents,
    fit,
    get_json,
    latest_pregame_ask,
    market_team,
    markets_for_day,
    mlb_games,
    play_states,
)
from edge_v07c_pregame_holdout import last_trade_before


def candle_bid(c):
    sec = c.get("yes_bid") or {}
    return cents(sec.get("close_dollars") if "close_dollars" in sec else sec.get("close"))


def sigmoid(x):
    return 1 / (1 + math.exp(-max(-12, min(12, x))))


def logit(p):
    p = max(.02, min(.98, p))
    return math.log(p / (1 - p))


def fair_away(pregame_away, away_score, home_score, inning, half, outs, base_run, late_run):
    completed = (max(1, inning) - 1) * 3 + (3 if str(half).lower() == "bottom" else 0) + outs
    rem = max(0, 27 - completed)
    frac = min(1, rem / 27)
    w = base_run + (late_run - base_run) * (1 - frac)
    return sigmoid(logit(pregame_away) + (away_score - home_score) * w)


def apply_model(rows, params):
    for r in rows:
        ap = fair_away(
            r["pregame_away"], r["away_score"], r["home_score"], r["inning"],
            r["half"], r["outs"], params["base_run"], params["late_run"],
        )
        q = ap if r["side"] == r["away"] else 1 - ap
        r["model_v08"] = round(q * 100, 2)
        r["edge_v08"] = round(q * 100 - r["ask"], 2)


def build_observations(days=24):
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    obs = []
    coverage = {
        "days": days,
        "games": 0,
        "matched_games": 0,
        "markets": 0,
        "candles": 0,
        "pregame_baselines": 0,
        "baseline_from_candle": 0,
        "baseline_from_trade": 0,
        "errors": [],
    }

    for i in range(days):
        day = start + timedelta(days=i)
        try:
            games = mlb_games(day)
            markets = markets_for_day(day)
        except Exception as exc:
            coverage["errors"].append({"date": str(day), "error": str(exc)})
            continue
        coverage["games"] += len(games)
        coverage["markets"] += len(markets)

        for game_pk, away, home, gstart in games:
            matched = [
                m for m in markets
                if str(m.get("event_ticker") or "").startswith("KXMLBGAME-")
                and away in str(m.get("event_ticker"))
                and home in str(m.get("event_ticker"))
                and market_team(m) in {away, home}
            ]
            if len(matched) < 2:
                continue
            try:
                states = play_states(game_pk)
            except Exception as exc:
                coverage["errors"].append({"game_pk": game_pk, "error": str(exc)})
                continue
            if not states:
                continue

            times = [x["ts"] for x in states]
            first_state_ts = times[0]
            hist = {m["ticker"]: candles(m, gstart - 7200, times[-1] + 900) for m in matched}
            coverage["candles"] += sum(len(v) for v in hist.values())
            side_market = {market_team(m): m for m in matched}
            am = side_market.get(away)
            hm = side_market.get(home)
            if not am or not hm:
                continue

            ap = latest_pregame_ask(hist.get(am["ticker"], []), first_state_ts)
            hp = latest_pregame_ask(hist.get(hm["ticker"], []), first_state_ts)
            source = "candle"
            if ap is None or hp is None:
                ap = last_trade_before(am["ticker"], gstart - 86400, first_state_ts)
                hp = last_trade_before(hm["ticker"], gstart - 86400, first_state_ts)
                source = "trade"
            if ap is None or hp is None or ap + hp <= 0:
                continue

            preaway = ap / (ap + hp)
            coverage["pregame_baselines"] += 1
            coverage["matched_games"] += 1
            coverage[f"baseline_from_{source}"] += 1

            for m in matched:
                side = market_team(m)
                result = str(m.get("result") or "").lower()
                if result not in {"yes", "no"}:
                    continue
                sidepre = 100 * (preaway if side == away else 1 - preaway)
                for c in hist.get(m["ticker"], []):
                    ts = int(c.get("end_period_ts") or 0)
                    ask = candle_ask(c)
                    bid = candle_bid(c)
                    idx = bisect.bisect_right(times, ts) - 1
                    if idx < 0 or ts <= first_state_ts or ask is None or not 1 <= ask <= 99:
                        continue
                    if bid is None or not 0 <= bid <= 99:
                        bid = max(0, ask - 2)
                    st = states[idx]
                    trailing = (
                        (side == away and st["away_score"] < st["home_score"])
                        or (side == home and st["home_score"] < st["away_score"])
                    )
                    obs.append({
                        "date": str(day), "game_pk": game_pk, "ticker": m["ticker"], "side": side,
                        "away": away, "home": home, "away_score": st["away_score"], "home_score": st["home_score"],
                        "inning": st["inning"], "half": st["half"], "outs": st["outs"], "ask": ask, "bid": bid,
                        "won": result == "yes", "ts": ts, "pregame_away": preaway, "pregame_side": round(sidepre, 2),
                        "trailing": trailing, "deficit": abs(st["away_score"] - st["home_score"]),
                        "baseline_source": source,
                    })
            time.sleep(.015)
    return start, end, obs, coverage


def first_entries(rows, threshold, focused=False):
    first = {}
    for r in sorted(rows, key=lambda x: x["ts"]):
        if r["edge_v08"] < threshold:
            continue
        if focused:
            drop = r["pregame_side"] - r["ask"]
            if not (
                r["pregame_side"] >= 55 and r["trailing"] and r["deficit"] in (1, 2)
                and 4 <= r["inning"] <= 6 and drop >= 12
            ):
                continue
        first.setdefault(r["ticker"], r)
    return list(first.values())


def settlement_pnl(entry, entry_friction=1.0):
    px = min(99.0, entry["ask"] + entry_friction)
    return (100 / px - 1) if entry["won"] else -1


def replay_trade(entry, series, entry_friction=1.0, exit_friction=0.5):
    entry_px = min(99.0, entry["ask"] + entry_friction)
    future = [r for r in series if r["ts"] > entry["ts"]]
    if not future:
        return None

    executable = [(r["ts"], max(0.0, r["bid"] - exit_friction), r) for r in future]
    best_ts, best_bid, _ = max(executable, key=lambda x: x[1])
    worst_ts, worst_bid, _ = min(executable, key=lambda x: x[1])

    def target(target_cents):
        goal = entry_px + target_cents
        hit = next((x for x in executable if x[1] >= goal), None)
        if hit:
            return {"hit": True, "exit_px": round(hit[1], 2), "minutes": round((hit[0] - entry["ts"]) / 60, 1), "pnl": round(hit[1] / entry_px - 1, 5)}
        return {"hit": False, "exit_px": 100 if entry["won"] else 0, "minutes": None, "pnl": round(settlement_pnl(entry, entry_friction), 5)}

    def roi_target(target_roi):
        goal = entry_px * (1 + target_roi)
        hit = next((x for x in executable if x[1] >= goal), None)
        if hit:
            return {"hit": True, "exit_px": round(hit[1], 2), "minutes": round((hit[0] - entry["ts"]) / 60, 1), "pnl": round(hit[1] / entry_px - 1, 5)}
        return {"hit": False, "exit_px": 100 if entry["won"] else 0, "minutes": None, "pnl": round(settlement_pnl(entry, entry_friction), 5)}

    # Exit when the market catches the model enough that the discrepancy is <=2 points.
    fair_hit = next((x for x in executable if x[2].get("edge_v08", 999) <= 2 and x[1] > entry_px), None)
    fair_exit = {
        "hit": bool(fair_hit),
        "exit_px": round(fair_hit[1], 2) if fair_hit else (100 if entry["won"] else 0),
        "minutes": round((fair_hit[0] - entry["ts"]) / 60, 1) if fair_hit else None,
        "pnl": round((fair_hit[1] / entry_px - 1) if fair_hit else settlement_pnl(entry, entry_friction), 5),
    }

    return {
        "ticker": entry["ticker"], "date": entry["date"], "side": entry["side"], "entry_ts": entry["ts"],
        "entry_ask": entry["ask"], "effective_entry": round(entry_px, 2), "entry_edge": entry["edge_v08"],
        "pregame_side": entry["pregame_side"], "inning": entry["inning"], "deficit": entry["deficit"],
        "trailing": entry["trailing"], "won": entry["won"],
        "mfe_cents": round(best_bid - entry_px, 2), "mfe_roi_pct": round(100 * (best_bid / entry_px - 1), 2),
        "mfe_minutes": round((best_ts - entry["ts"]) / 60, 1),
        "mae_cents": round(worst_bid - entry_px, 2), "mae_roi_pct": round(100 * (worst_bid / entry_px - 1), 2),
        "settlement_pnl": round(settlement_pnl(entry, entry_friction), 5),
        "targets": {str(x): target(x) for x in (5, 10, 15, 20)},
        "roi_targets": {"25": roi_target(.25), "50": roi_target(.50)},
        "fair_value_exit": fair_exit,
    }


def summarize_replays(replays):
    if not replays:
        return {"trades": 0}

    def agg(path, key=None):
        vals = []
        hits = 0
        mins = []
        for r in replays:
            d = r[path] if key is None else r[path][key]
            vals.append(d["pnl"])
            if d["hit"]:
                hits += 1
                if d["minutes"] is not None:
                    mins.append(d["minutes"])
        return {
            "hit_rate_pct": round(100 * hits / len(replays), 2),
            "roi_pct": round(100 * sum(vals) / len(vals), 2),
            "avg_minutes_to_hit": round(sum(mins) / len(mins), 1) if mins else None,
        }

    settlement = [r["settlement_pnl"] for r in replays]
    positive_mfe = sum(1 for r in replays if r["mfe_cents"] > 0)
    mfe5 = sum(1 for r in replays if r["mfe_cents"] >= 5)
    mfe10 = sum(1 for r in replays if r["mfe_cents"] >= 10)
    return {
        "trades": len(replays),
        "settlement_roi_pct": round(100 * sum(settlement) / len(settlement), 2),
        "any_positive_rebound_pct": round(100 * positive_mfe / len(replays), 2),
        "rebound_5c_pct": round(100 * mfe5 / len(replays), 2),
        "rebound_10c_pct": round(100 * mfe10 / len(replays), 2),
        "avg_mfe_cents": round(sum(r["mfe_cents"] for r in replays) / len(replays), 2),
        "median_mfe_cents": round(sorted(r["mfe_cents"] for r in replays)[len(replays)//2], 2),
        "avg_mae_cents": round(sum(r["mae_cents"] for r in replays) / len(replays), 2),
        "exit_plus_5c": agg("targets", "5"),
        "exit_plus_10c": agg("targets", "10"),
        "exit_plus_15c": agg("targets", "15"),
        "exit_plus_20c": agg("targets", "20"),
        "exit_plus_25pct": agg("roi_targets", "25"),
        "exit_plus_50pct": agg("roi_targets", "50"),
        "exit_when_edge_closes": agg("fair_value_exit"),
    }


def run(days=24):
    start, end, obs, coverage = build_observations(days)
    dates = sorted({r["date"] for r in obs})
    cut = max(1, int(len(dates) * .60))
    train_dates, hold_dates = set(dates[:cut]), set(dates[cut:])
    train = [r for r in obs if r["date"] in train_dates]
    hold = [r for r in obs if r["date"] in hold_dates]

    params = fit(train)
    apply_model(train, params)
    apply_model(hold, params)

    by_ticker_train = defaultdict(list)
    by_ticker_hold = defaultdict(list)
    for r in train:
        by_ticker_train[r["ticker"]].append(r)
    for r in hold:
        by_ticker_hold[r["ticker"]].append(r)
    for rows in list(by_ticker_train.values()) + list(by_ticker_hold.values()):
        rows.sort(key=lambda x: x["ts"])

    def pack(rows, grouped):
        out = {}
        for focused_name, focused in (("all", False), ("focused_comeback", True)):
            out[focused_name] = {}
            for th in (5, 8, 10):
                entries = first_entries(rows, th, focused)
                replays = [replay_trade(e, grouped[e["ticker"]]) for e in entries]
                replays = [r for r in replays if r]
                out[focused_name][str(th)] = summarize_replays(replays)
        return out

    result = {
        "period": {"start": str(start), "end": str(end)},
        "coverage": coverage,
        "model": {
            "version": "EDGE-MLB-v0.8-reversion-research",
            "pregame_baseline": "normalized last quote/trade before first completed MLB play",
            "fit": params,
            "split": "chronological 60% train / 40% untouched holdout",
            "entry_friction_cents": 1.0,
            "exit_friction_cents": 0.5,
        },
        "results": {
            "train": {"dates": [min(train_dates, default=None), max(train_dates, default=None)], "observations": len(train), **pack(train, by_ticker_train)},
            "holdout": {"dates": [min(hold_dates, default=None), max(hold_dates, default=None)], "observations": len(hold), **pack(hold, by_ticker_hold)},
        },
        "limitations": [
            "Research only; no live orders are placed.",
            "Historical one-minute bid/ask candles approximate executable prices and may not capture queue position or fill probability.",
            "Entry friction +1.0c and exit friction -0.5c are modeled in addition to the observed spread.",
            "Pitcher, bullpen, lineup, injuries, liquidity depth and explicit Kalshi fee formulas are not yet modeled.",
            "Target exits fall back to settlement if the target was never reached.",
        ],
    }
    Path("edge_v08_results.json").write_text(json.dumps(result, indent=2))

    # Preserve a compact audit sample of untouched replays for manual inspection.
    sample = []
    for th in (5, 8, 10):
        for e in first_entries(hold, th, False)[:50]:
            r = replay_trade(e, by_ticker_hold[e["ticker"]])
            if r:
                r["threshold"] = th
                sample.append(r)
    Path("edge_v08_holdout_replays.json").write_text(json.dumps(sample[:150], indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run(int(os.environ.get("EDGE_DAYS", "24")))
