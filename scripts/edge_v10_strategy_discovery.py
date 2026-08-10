from __future__ import annotations

import json
import os
from collections import defaultdict
from itertools import product
from pathlib import Path

from edge_v07_pregame_holdout import fit
from edge_v08b_reversion import corrected_build_observations
from edge_v09_focused_reversion import apply_model, executable_bid

ENTRY_FRICTION = 1.0
EXIT_FRICTION = 0.5
MAX_HOLD = 30


def grouped(rows):
    out = defaultdict(list)
    for r in rows:
        out[r["ticker"]].append(r)
    for values in out.values():
        values.sort(key=lambda x: x["ts"])
    return out


def enrich(rows):
    for r in rows:
        r["drop"] = round(r["pregame_side"] - r["ask"], 2)
        r["batting"] = (
            (r["side"] == r["away"] and str(r["half"]).lower() == "top")
            or (r["side"] == r["home"] and str(r["half"]).lower() == "bottom")
        )
        r["home_side"] = r["side"] == r["home"]
        r["edge"] = r.get("edge_v09", 0)


def rule_match(r, rule):
    lo, hi = rule["pregame"]
    return (
        lo <= r["pregame_side"] < hi
        and r["trailing"]
        and r["deficit"] in rule["deficits"]
        and rule["innings"][0] <= r["inning"] <= rule["innings"][1]
        and r["drop"] >= rule["drop_min"]
        and r["edge"] >= rule["edge_min"]
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
        r = next((x for x in future if x["ts"] >= target), future[-1])
        px = executable_bid(r)
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
        "pregame": entry["pregame_side"], "deficit": entry["deficit"], "inning": entry["inning"],
        "drop": entry["drop"], "edge": entry["edge"], "batting": entry["batting"],
    }


def stats(replays, exit_key):
    vals = [r[exit_key] for r in replays]
    if not vals:
        return {"trades": 0, "roi_pct": None}
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for v in vals:
        equity += v / 100
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return {
        "trades": len(vals),
        "roi_pct": round(sum(vals) / len(vals), 2),
        "positive_trade_pct": round(100 * sum(v > 0 for v in vals) / len(vals), 2),
        "avg_mfe_cents": round(sum(r["mfe"] for r in replays) / len(replays), 2),
        "avg_mae_cents": round(sum(r["mae"] for r in replays) / len(replays), 2),
        "max_drawdown_$1_units": round(max_dd, 2),
    }


def build_rules():
    strengths = [(55, 65), (58, 65), (60, 65), (60, 68), (55, 70)]
    deficits = [(1,), (2,), (1, 2)]
    innings = [(4, 6), (4, 5), (5, 6)]
    drops = [12, 18, 24]
    edges = [3, 5, 8]
    batting = [None, True]
    rules = []
    for pre, de, inn, drop, edge, bat in product(strengths, deficits, innings, drops, edges, batting):
        rules.append({"pregame": pre, "deficits": de, "innings": inn, "drop_min": drop, "edge_min": edge, "batting": bat})
    return rules


def evaluate(rows, grp, rule):
    es = entries(rows, rule)
    reps = [replay(e, grp[e["ticker"]]) for e in es]
    return [r for r in reps if r]


def run(days=120):
    start, end, obs, coverage = corrected_build_observations(days)
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
    for rule in build_rules():
        dr, vr = evaluate(dev, dg, rule), evaluate(val, vg, rule)
        if len(dr) < 15 or len(vr) < 8:
            continue
        for exit_key in exits:
            ds, vs = stats(dr, exit_key), stats(vr, exit_key)
            if ds["roi_pct"] is None or vs["roi_pct"] is None:
                continue
            # Robustness first: require both periods positive and rank by weaker period.
            if ds["roi_pct"] <= 0 or vs["roi_pct"] <= 0:
                continue
            score = min(ds["roi_pct"], vs["roi_pct"]) + 0.20 * ((ds["roi_pct"] + vs["roi_pct"]) / 2)
            candidates.append({"score": round(score, 3), "rule": rule, "exit": exit_key, "development": ds, "validation": vs})

    candidates.sort(key=lambda x: (x["score"], x["validation"]["trades"]), reverse=True)
    top = candidates[:25]
    winner = top[0] if top else None
    final = None
    final_replays = []
    if winner:
        final_replays = evaluate(hold, hg, winner["rule"])
        final = stats(final_replays, winner["exit"])

    result = {
        "version": "EDGE-MLB-v1.0-strategy-discovery",
        "period": {"start": str(start), "end": str(end), "requested_days": days},
        "coverage": coverage,
        "split": {
            "method": "chronological 50% development / 25% validation / 25% final untouched holdout",
            "development_dates": [min(dev_dates, default=None), max(dev_dates, default=None)],
            "validation_dates": [min(val_dates, default=None), max(val_dates, default=None)],
            "holdout_dates": [min(hold_dates, default=None), max(hold_dates, default=None)],
            "observations": {"development": len(dev), "validation": len(val), "holdout": len(hold)},
        },
        "model_fit": params,
        "search": {"rules_tested": len(build_rules()), "exit_styles": exits, "qualified_robust_candidates": len(candidates)},
        "selected_strategy": winner,
        "final_untouched_result": final,
        "top_candidates_before_holdout": top,
        "interpretation_guardrails": [
            "Final holdout is never used to select the strategy.",
            "A positive final result is evidence for further paper validation, not proof of future profitability.",
            "Observed bid/ask candles plus +1c entry and -0.5c exit friction are used; queue/fill risk and explicit fees remain limitations.",
            "No live orders or live-money automation are enabled by this research runner.",
        ],
    }
    Path("edge_v10_results.json").write_text(json.dumps(result, indent=2))
    Path("edge_v10_final_holdout_replays.json").write_text(json.dumps(final_replays, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run(int(os.environ.get("EDGE_DAYS", "120")))
