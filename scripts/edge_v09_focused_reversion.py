from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

import edge_v08_reversion as model
from edge_v08b_reversion import corrected_build_observations
from edge_v07_pregame_holdout import fit

ENTRY_FRICTION = 1.0
EXIT_FRICTION = 0.5
MAX_HOLD_MINUTES = 30


def apply_model(rows, params):
    for r in rows:
        away_p = model.fair_away(
            r["pregame_away"], r["away_score"], r["home_score"],
            r["inning"], r["half"], r["outs"], params["base_run"], params["late_run"],
        )
        p = away_p if r["side"] == r["away"] else 1 - away_p
        r["model_v09"] = round(100 * p, 2)
        r["edge_v09"] = round(100 * p - r["ask"], 2)
        r["drop_from_pregame"] = round(r["pregame_side"] - r["ask"], 2)
        r["is_home"] = r["side"] == r["home"]
        r["batting"] = (
            (r["side"] == r["away"] and str(r["half"]).lower() == "top")
            or (r["side"] == r["home"] and str(r["half"]).lower() == "bottom")
        )


def primary_rule(r):
    return (
        r["pregame_side"] >= 55
        and r["trailing"]
        and r["deficit"] in (1, 2)
        and 4 <= r["inning"] <= 6
        and r["drop_from_pregame"] >= 12
        and r["edge_v09"] >= 5
    )


def first_entries(rows, predicate):
    first = {}
    for r in sorted(rows, key=lambda x: x["ts"]):
        if predicate(r):
            first.setdefault(r["ticker"], r)
    return list(first.values())


def executable_bid(r):
    return max(0.0, float(r["bid"]) - EXIT_FRICTION)


def replay(entry, series):
    entry_px = min(99.0, float(entry["ask"]) + ENTRY_FRICTION)
    future = [r for r in series if r["ts"] > entry["ts"]]
    if not future:
        return None

    within = [r for r in future if r["ts"] <= entry["ts"] + MAX_HOLD_MINUTES * 60]
    if not within:
        within = future[:1]

    def first_at(minutes):
        target_ts = entry["ts"] + minutes * 60
        row = next((r for r in future if r["ts"] >= target_ts), future[-1])
        px = executable_bid(row)
        return {
            "exit_px": round(px, 2),
            "roi_pct": round(100 * (px / entry_px - 1), 2),
            "actual_minutes": round((row["ts"] - entry["ts"]) / 60, 1),
        }

    fallback = first_at(MAX_HOLD_MINUTES)

    def target_exit(cents):
        goal = entry_px + cents
        hit = next((r for r in within if executable_bid(r) >= goal), None)
        if hit:
            px = executable_bid(hit)
            return {
                "hit": True,
                "exit_px": round(px, 2),
                "roi_pct": round(100 * (px / entry_px - 1), 2),
                "minutes": round((hit["ts"] - entry["ts"]) / 60, 1),
            }
        return {"hit": False, **fallback, "minutes": fallback["actual_minutes"]}

    best = max(within, key=executable_bid)
    worst = min(within, key=executable_bid)
    best_px, worst_px = executable_bid(best), executable_bid(worst)

    return {
        "ticker": entry["ticker"], "date": entry["date"], "side": entry["side"],
        "entry_ts": entry["ts"], "effective_entry": round(entry_px, 2),
        "pregame_side": entry["pregame_side"], "drop_from_pregame": entry["drop_from_pregame"],
        "edge": entry["edge_v09"], "deficit": entry["deficit"], "inning": entry["inning"],
        "outs": entry["outs"], "is_home": entry["is_home"], "batting": entry["batting"],
        "won_game": entry["won"],
        "mfe_30m_cents": round(best_px - entry_px, 2),
        "mfe_30m_roi_pct": round(100 * (best_px / entry_px - 1), 2),
        "mfe_30m_minutes": round((best["ts"] - entry["ts"]) / 60, 1),
        "mae_30m_cents": round(worst_px - entry_px, 2),
        "mae_30m_roi_pct": round(100 * (worst_px / entry_px - 1), 2),
        "fixed_exit": {str(m): first_at(m) for m in (5, 10, 15, 30)},
        "target_exit": {str(c): target_exit(c) for c in (3, 5, 7, 10)},
    }


def avg(values):
    return round(sum(values) / len(values), 2) if values else None


def summarize(replays):
    if not replays:
        return {"trades": 0}
    out = {
        "trades": len(replays),
        "game_win_rate_pct": round(100 * sum(r["won_game"] for r in replays) / len(replays), 2),
        "any_positive_rebound_30m_pct": round(100 * sum(r["mfe_30m_cents"] > 0 for r in replays) / len(replays), 2),
        "avg_mfe_30m_cents": avg([r["mfe_30m_cents"] for r in replays]),
        "median_mfe_30m_cents": sorted(r["mfe_30m_cents"] for r in replays)[len(replays)//2],
        "avg_mae_30m_cents": avg([r["mae_30m_cents"] for r in replays]),
        "fixed_exits": {},
        "target_exits": {},
    }
    for m in (5, 10, 15, 30):
        vals = [r["fixed_exit"][str(m)]["roi_pct"] for r in replays]
        out["fixed_exits"][str(m)] = {"roi_pct": avg(vals)}
    for c in (3, 5, 7, 10):
        ds = [r["target_exit"][str(c)] for r in replays]
        out["target_exits"][str(c)] = {
            "hit_rate_pct": round(100 * sum(d["hit"] for d in ds) / len(ds), 2),
            "roi_pct": avg([d["roi_pct"] for d in ds]),
            "avg_minutes_when_hit": avg([d["minutes"] for d in ds if d["hit"]]),
        }
    return out


def segment_summary(rows, grouped, predicate):
    entries = first_entries(rows, lambda r: primary_rule(r) and predicate(r))
    reps = [replay(e, grouped[e["ticker"]]) for e in entries]
    return summarize([r for r in reps if r])


def run(days=60):
    start, end, obs, coverage = corrected_build_observations(days)
    dates = sorted({r["date"] for r in obs})
    cut = max(1, int(len(dates) * .65))
    train_dates = set(dates[:cut])
    hold_dates = set(dates[cut:])
    train = [r for r in obs if r["date"] in train_dates]
    holdout = [r for r in obs if r["date"] in hold_dates]

    params = fit(train)
    apply_model(train, params)
    apply_model(holdout, params)

    def grouped(rows):
        d = defaultdict(list)
        for r in rows:
            d[r["ticker"]].append(r)
        for vals in d.values():
            vals.sort(key=lambda x: x["ts"])
        return d

    train_grouped = grouped(train)
    hold_grouped = grouped(holdout)

    train_entries = first_entries(train, primary_rule)
    hold_entries = first_entries(holdout, primary_rule)
    train_replays = [replay(e, train_grouped[e["ticker"]]) for e in train_entries]
    hold_replays = [replay(e, hold_grouped[e["ticker"]]) for e in hold_entries]
    train_replays = [r for r in train_replays if r]
    hold_replays = [r for r in hold_replays if r]

    def buckets(rows, grp):
        return {
            "pregame_strength": {
                "55_60": segment_summary(rows, grp, lambda r: 55 <= r["pregame_side"] < 60),
                "60_65": segment_summary(rows, grp, lambda r: 60 <= r["pregame_side"] < 65),
                "65_70": segment_summary(rows, grp, lambda r: 65 <= r["pregame_side"] < 70),
                "70_plus": segment_summary(rows, grp, lambda r: r["pregame_side"] >= 70),
            },
            "deficit": {
                "down_1": segment_summary(rows, grp, lambda r: r["deficit"] == 1),
                "down_2": segment_summary(rows, grp, lambda r: r["deficit"] == 2),
            },
            "inning": {
                "4": segment_summary(rows, grp, lambda r: r["inning"] == 4),
                "5": segment_summary(rows, grp, lambda r: r["inning"] == 5),
                "6": segment_summary(rows, grp, lambda r: r["inning"] == 6),
            },
            "side_context": {
                "home": segment_summary(rows, grp, lambda r: r["is_home"]),
                "away": segment_summary(rows, grp, lambda r: not r["is_home"]),
                "batting": segment_summary(rows, grp, lambda r: r["batting"]),
                "fielding": segment_summary(rows, grp, lambda r: not r["batting"]),
            },
            "market_drop": {
                "12_20": segment_summary(rows, grp, lambda r: 12 <= r["drop_from_pregame"] < 20),
                "20_30": segment_summary(rows, grp, lambda r: 20 <= r["drop_from_pregame"] < 30),
                "30_plus": segment_summary(rows, grp, lambda r: r["drop_from_pregame"] >= 30),
            },
        }

    result = {
        "version": "EDGE-MLB-v0.9-focused-reversion",
        "period": {"start": str(start), "end": str(end), "days": days},
        "coverage": coverage,
        "split": {
            "method": "chronological 65% development / 35% untouched holdout",
            "train_dates": [min(train_dates) if train_dates else None, max(train_dates) if train_dates else None],
            "holdout_dates": [min(hold_dates) if hold_dates else None, max(hold_dates) if hold_dates else None],
            "train_observations": len(train), "holdout_observations": len(holdout),
        },
        "model_fit": params,
        "primary_rule": {
            "definition": "pregame >=55%; trailing 1-2; innings 4-6; >=12pt market drop; model edge >=5pt",
            "entry_friction_cents": ENTRY_FRICTION,
            "exit_friction_cents": EXIT_FRICTION,
            "max_hold_minutes": MAX_HOLD_MINUTES,
            "development": summarize(train_replays),
            "holdout": summarize(hold_replays),
        },
        "holdout_segments": buckets(holdout, hold_grouped),
        "limitations": [
            "Research only; no live orders or live-signal promotion.",
            "Segment tables are exploratory; small buckets must not be treated as validated strategies.",
            "Pitcher, bullpen, lineup, injuries, and liquidity depth are not yet modeled.",
            "One-minute candles can miss sub-minute price paths.",
        ],
    }

    Path("edge_v09_results.json").write_text(json.dumps(result, indent=2))
    Path("edge_v09_holdout_replays.json").write_text(json.dumps(hold_replays, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run(int(os.environ.get("EDGE_DAYS", "60")))
