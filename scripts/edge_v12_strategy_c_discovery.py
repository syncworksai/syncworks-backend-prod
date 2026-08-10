from __future__ import annotations

import json
import os
from collections import defaultdict
from itertools import product
from pathlib import Path

import edge_v08b_reversion as observation_source
import edge_v10b_strategy_discovery as archive
from edge_v07_pregame_holdout import fit
from edge_v09_focused_reversion import apply_model, executable_bid

ENTRY_FRICTION = 1.0
MAX_HOLD = 30


def grouped(rows):
    out = defaultdict(list)
    for r in rows:
        out[r["ticker"]].append(r)
    for vals in out.values():
        vals.sort(key=lambda x: x["ts"])
    return out


def enrich(rows):
    for r in rows:
        side_score = r["away_score"] if r["side"] == r["away"] else r["home_score"]
        opp_score = r["home_score"] if r["side"] == r["away"] else r["away_score"]
        margin = side_score - opp_score
        r["margin"] = margin
        r["batting"] = ((r["side"] == r["away"] and str(r["half"]).lower() == "top") or (r["side"] == r["home"] and str(r["half"]).lower() == "bottom"))
        r["move_from_pregame"] = round(r["ask"] - r["pregame_side"], 2)
        r["edge"] = r.get("edge_v09", 0)


def state_match(r, mode):
    if mode == "TIED":
        return r["margin"] == 0
    if mode == "LEAD_1":
        return r["margin"] == 1
    if mode == "LEAD_1_2":
        return r["margin"] in (1, 2)
    return False


def rule_match(r, rule):
    lo, hi = rule["pregame"]
    cap = rule["max_move_above_pregame"]
    return (
        lo <= r["pregame_side"] < hi
        and state_match(r, rule["state"])
        and rule["innings"][0] <= r["inning"] <= rule["innings"][1]
        and r["edge"] >= rule["edge_min"]
        and (cap is None or r["move_from_pregame"] <= cap)
        and (rule["batting"] is None or r["batting"] == rule["batting"])
    )


def entries(rows, rule):
    first = {}
    for r in sorted(rows, key=lambda x: x["ts"]):
        if rule_match(r, rule):
            first.setdefault(r["ticker"], r)
    return list(first.values())


def replay(entry, series):
    entry_px = min(99.0, float(entry["ask"]) + ENTRY_FRICTION)
    future = [r for r in series if r["ts"] > entry["ts"]]
    if not future:
        return None
    window = [r for r in future if r["ts"] <= entry["ts"] + MAX_HOLD * 60]
    if not window:
        return None

    def at(minutes):
        target = entry["ts"] + minutes * 60
        row = next((x for x in future if x["ts"] >= target), future[-1])
        px = executable_bid(row)
        return 100 * (px / entry_px - 1)

    fallback = at(30)

    def target(cents):
        goal = entry_px + cents
        hit = next((x for x in window if executable_bid(x) >= goal), None)
        if not hit:
            return fallback
        return 100 * (executable_bid(hit) / entry_px - 1)

    best = max(executable_bid(x) for x in window)
    worst = min(executable_bid(x) for x in window)
    return {
        "fixed10": at(10), "fixed15": at(15), "fixed20": at(20), "fixed30": fallback,
        "target7": target(7), "target10": target(10),
        "mfe": best - entry_px, "mae": worst - entry_px,
        "date": entry["date"], "ticker": entry["ticker"], "side": entry["side"],
        "pregame": entry["pregame_side"], "margin": entry["margin"], "inning": entry["inning"],
        "move_from_pregame": entry["move_from_pregame"], "edge": entry["edge"], "batting": entry["batting"],
    }


def stats(replays, exit_key):
    vals = [r[exit_key] for r in replays]
    if not vals:
        return {"trades": 0, "roi_pct": None}
    equity = peak = max_dd = 0.0
    for v in vals:
        equity += v / 100
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    positives = [v for v in vals if v > 0]
    negatives = [v for v in vals if v <= 0]
    return {
        "trades": len(vals),
        "roi_pct": round(sum(vals) / len(vals), 2),
        "positive_trade_pct": round(100 * len(positives) / len(vals), 2),
        "avg_positive_roi_pct": round(sum(positives) / len(positives), 2) if positives else None,
        "avg_negative_roi_pct": round(sum(negatives) / len(negatives), 2) if negatives else None,
        "avg_mfe_cents": round(sum(r["mfe"] for r in replays) / len(replays), 2),
        "avg_mae_cents": round(sum(r["mae"] for r in replays) / len(replays), 2),
        "max_drawdown_$1_units": round(max_dd, 2),
    }


def build_rules():
    strengths = [(35,45),(40,50),(45,55),(50,60),(55,65),(65,75),(75,90)]
    states = ["TIED", "LEAD_1", "LEAD_1_2"]
    innings = [(3,5),(4,6),(5,7),(6,8)]
    edges = [3,5,8]
    caps = [0,5,10,20,None]
    batting = [None, True, False]
    return [
        {"pregame": pre, "state": state, "innings": inn, "edge_min": edge, "max_move_above_pregame": cap, "batting": bat}
        for pre, state, inn, edge, cap, bat in product(strengths, states, innings, edges, caps, batting)
    ]


def evaluate(rows, grp, rule):
    reps = [replay(e, grp[e["ticker"]]) for e in entries(rows, rule)]
    return [r for r in reps if r]


def run(days=120):
    observation_source.markets_for_day = archive.combined_markets_for_day
    start, end, obs, coverage = observation_source.corrected_build_observations(days)
    dates = sorted({r["date"] for r in obs})
    n = len(dates)
    c1, c2 = max(1, int(n * .50)), max(2, int(n * .75))
    dev_dates, val_dates, hold_dates = set(dates[:c1]), set(dates[c1:c2]), set(dates[c2:])
    dev = [r for r in obs if r["date"] in dev_dates]
    val = [r for r in obs if r["date"] in val_dates]
    hold = [r for r in obs if r["date"] in hold_dates]

    params = fit(dev)
    for rows in (dev, val, hold):
        apply_model(rows, params)
        enrich(rows)
    dg, vg, hg = grouped(dev), grouped(val), grouped(hold)

    exits = ["fixed10", "fixed15", "fixed20", "fixed30", "target7", "target10"]
    candidates = []
    rules = build_rules()
    for rule in rules:
        dr, vr = evaluate(dev, dg, rule), evaluate(val, vg, rule)
        if len(dr) < 15 or len(vr) < 8:
            continue
        for exit_key in exits:
            ds, vs = stats(dr, exit_key), stats(vr, exit_key)
            if ds["roi_pct"] is None or vs["roi_pct"] is None or ds["roi_pct"] <= 0 or vs["roi_pct"] <= 0:
                continue
            score = min(ds["roi_pct"], vs["roi_pct"]) + 0.20 * ((ds["roi_pct"] + vs["roi_pct"]) / 2)
            candidates.append({"score": round(score,3), "rule": rule, "exit": exit_key, "development": ds, "validation": vs})

    candidates.sort(key=lambda x: (x["score"], x["validation"]["trades"]), reverse=True)
    winner = candidates[0] if candidates else None
    final_replays = evaluate(hold, hg, winner["rule"]) if winner else []
    final = stats(final_replays, winner["exit"]) if winner else None
    result = {
        "version": "EDGE-MLB-v1.2-strategy-c-discovery",
        "hypothesis": "Independent continuation/underreaction regime: tied or leading side only; no trailing comeback entries.",
        "period": {"start": str(start), "end": str(end), "requested_days": days},
        "coverage": coverage,
        "split": {"method": "chronological 50% development / 25% validation / 25% final untouched holdout", "development_dates": [min(dev_dates,default=None),max(dev_dates,default=None)], "validation_dates": [min(val_dates,default=None),max(val_dates,default=None)], "holdout_dates": [min(hold_dates,default=None),max(hold_dates,default=None)]},
        "search": {"rules_tested": len(rules), "exit_styles": exits, "qualified_robust_candidates": len(candidates)},
        "selected_strategy": winner,
        "final_untouched_result": final,
        "top_candidates_before_holdout": candidates[:25],
        "guardrails": ["Strategy A and B are not modified by this search.", "Final holdout is never used to choose Strategy C.", "Positive backtest evidence is not proof of future profitability.", "No live-money execution is enabled."],
    }
    Path("edge_v12_strategy_c_results.json").write_text(json.dumps(result, indent=2))
    Path("edge_v12_strategy_c_holdout_replays.json").write_text(json.dumps(final_replays, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run(int(os.environ.get("EDGE_DAYS", "120")))
