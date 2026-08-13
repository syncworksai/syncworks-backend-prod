from __future__ import annotations

import bisect
import json
import math
import os
from collections import defaultdict
from itertools import product
from pathlib import Path

import edge_v08b_reversion as source
import edge_v10b_strategy_discovery as archive
from edge_v07_pregame_holdout import MLB_FEED, get_json, logit, sigmoid

ENTRY_FRICTION_CENTS = 1.5


def pitcher_timeline(game_pk):
    payload = get_json(MLB_FEED.format(game_pk=game_pk))
    plays = payload.get("liveData", {}).get("plays", {}).get("allPlays", [])
    rows = []
    pitch_counts = defaultdict(int)
    starters = {}
    for play in plays:
        about = play.get("about") or {}
        events = play.get("playEvents") or []
        if not events or not about.get("isComplete"):
            continue
        end = events[-1].get("endTime")
        if not end:
            continue
        from edge_v07_pregame_holdout import dt
        when = dt(end)
        if not when:
            continue
        matchup = play.get("matchup") or {}
        pitcher = matchup.get("pitcher") or {}
        pid = pitcher.get("id")
        if not pid:
            continue
        half = str(about.get("halfInning") or "").lower()
        defense = "home" if half == "top" else "away"
        starters.setdefault(defense, pid)
        for ev in events:
            if ev.get("isPitch"):
                pitch_counts[pid] += 1
        rows.append({
            "ts": when.timestamp(),
            "defense": defense,
            "pitcher_id": pid,
            "pitcher_name": pitcher.get("fullName"),
            "pitch_count": pitch_counts[pid],
            "starter_active": starters.get(defense) == pid,
        })
    return sorted(rows, key=lambda r: r["ts"])


def enrich_pitchers(obs):
    by_game = defaultdict(list)
    for r in obs:
        by_game[r["game_pk"]].append(r)
    coverage = {"games_requested": len(by_game), "games_with_pitcher_timeline": 0, "observations_enriched": 0, "errors": []}
    for game_pk, rows in by_game.items():
        try:
            timeline = pitcher_timeline(game_pk)
        except Exception as exc:
            coverage["errors"].append({"game_pk": game_pk, "error": str(exc)})
            continue
        if not timeline:
            continue
        coverage["games_with_pitcher_timeline"] += 1
        times = [x["ts"] for x in timeline]
        for r in rows:
            idx = bisect.bisect_right(times, r["ts"]) - 1
            if idx < 0:
                continue
            p = timeline[idx]
            defensive_team = r["home"] if p["defense"] == "home" else r["away"]
            sign = 1.0 if r["side"] == defensive_team else -1.0
            r["pitcher_id"] = p["pitcher_id"]
            r["pitcher_name"] = p["pitcher_name"]
            r["pitch_count"] = p["pitch_count"]
            r["starter_active"] = p["starter_active"]
            r["pitching_sign"] = sign
            coverage["observations_enriched"] += 1
    return coverage


def fair_side(r, base_run, late_run, starter_coef=0.0, pitch_coef=0.0):
    completed = (max(1, int(r["inning"])) - 1) * 3 + (3 if str(r["half"]).lower() == "bottom" else 0) + int(r["outs"])
    rem = max(0, 27 - completed)
    frac = min(1.0, rem / 27.0)
    run_weight = base_run + (late_run - base_run) * (1 - frac)
    away_logit = logit(float(r["pregame_away"])) + (float(r["away_score"]) - float(r["home_score"])) * run_weight
    side_logit = away_logit if r["side"] == r["away"] else -away_logit
    if r.get("pitching_sign") is not None:
        sign = float(r["pitching_sign"])
        if r.get("starter_active"):
            side_logit += sign * starter_coef
        pc = float(r.get("pitch_count") or 0)
        fatigue = max(0.0, min(1.5, (pc - 65.0) / 35.0))
        side_logit -= sign * pitch_coef * fatigue
    return sigmoid(side_logit)


def unique_fit_rows(rows):
    uniq = {}
    for r in sorted(rows, key=lambda x: x["ts"]):
        uniq.setdefault((r["ticker"], r["inning"]), r)
    return list(uniq.values())


def brier(rows, cfg):
    vals = []
    for r in unique_fit_rows(rows):
        p = fair_side(r, **cfg)
        y = 1.0 if r["won"] else 0.0
        vals.append((p - y) ** 2)
    return sum(vals) / len(vals) if vals else 1.0


def fit(rows, pitcher_aware=False):
    grids = product(
        (.16, .20, .24, .28, .32),
        (.48, .60, .72, .84, 1.00),
        (0.0, .05, .10, .15, .20) if pitcher_aware else (0.0,),
        (0.0, .04, .08, .12, .16) if pitcher_aware else (0.0,),
    )
    scored = []
    for base_run, late_run, starter_coef, pitch_coef in grids:
        cfg = {"base_run": base_run, "late_run": late_run, "starter_coef": starter_coef, "pitch_coef": pitch_coef}
        scored.append((brier(rows, cfg), cfg))
    scored.sort(key=lambda x: x[0])
    return {**scored[0][1], "train_brier": round(scored[0][0], 6)}


def replay(rows, cfg, threshold):
    first = {}
    for r in sorted(rows, key=lambda x: x["ts"]):
        ask = float(r["ask"])
        p = fair_side(r, **{k: cfg[k] for k in ("base_run", "late_run", "starter_coef", "pitch_coef")}) * 100.0
        edge = p - ask
        if edge < threshold or ask + ENTRY_FRICTION_CENTS >= 100:
            continue
        first.setdefault(r["game_pk"], {**r, "model_pct": p, "edge_pct": edge})
    trades = list(first.values())
    pnl = []
    equity = peak = max_dd = 0.0
    wins = 0
    for r in trades:
        entry = min(99.0, float(r["ask"]) + ENTRY_FRICTION_CENTS)
        trade_pnl = (100.0 / entry - 1.0) if r["won"] else -1.0
        pnl.append(trade_pnl)
        wins += int(r["won"])
        equity += trade_pnl
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return {
        "trades": len(trades),
        "wins": wins,
        "win_rate_pct": round(100 * wins / len(trades), 2) if trades else None,
        "net_units": round(sum(pnl), 3),
        "roi_pct": round(100 * sum(pnl) / len(trades), 2) if trades else None,
        "max_drawdown_units": round(max_dd, 3),
        "avg_model_edge_pct": round(sum(r["edge_pct"] for r in trades) / len(trades), 2) if trades else None,
    }


def pack(rows, cfg):
    return {
        "brier": round(brier(rows, cfg), 6),
        "thresholds": {str(t): replay(rows, cfg, t) for t in (5, 8, 10, 12)},
    }


def run(days=60):
    source.markets_for_day = archive.combined_markets_for_day
    start, end, obs, coverage = source.corrected_build_observations(days)
    pitcher_coverage = enrich_pitchers(obs)
    dates = sorted({r["date"] for r in obs})
    c1 = max(1, int(len(dates) * .50))
    c2 = max(c1 + 1, int(len(dates) * .75))
    dev_dates, val_dates, hold_dates = set(dates[:c1]), set(dates[c1:c2]), set(dates[c2:])
    dev = [r for r in obs if r["date"] in dev_dates]
    val = [r for r in obs if r["date"] in val_dates]
    hold = [r for r in obs if r["date"] in hold_dates]

    f1 = fit(dev, pitcher_aware=False)
    f2 = fit(dev, pitcher_aware=True)
    result = {
        "version": "EDGE-MLB-v1.6-Strategy-F",
        "period": [str(start), str(end)],
        "coverage": coverage,
        "pitcher_coverage": pitcher_coverage,
        "split": "50% development / 25% validation / 25% untouched holdout",
        "models": {
            "F1_GAME_STATE": {"features": ["pregame probability", "score", "inning", "half", "outs"], "fit": f1, "development": pack(dev, f1), "validation": pack(val, f1), "holdout": pack(hold, f1)},
            "F2_PITCHER_AWARE": {"features": ["F1 features", "current pitcher identity", "starter still active", "current pitcher pitch count/fatigue proxy"], "fit": f2, "development": pack(dev, f2), "validation": pack(val, f2), "holdout": pack(hold, f2)},
        },
        "guardrails": [
            "Final 25% of dates is untouched by coefficient fitting.",
            "One simulated entry maximum per game per threshold.",
            "Entry friction is +1.5 cents and positions settle at game result.",
            "F remains research-only and is not frozen or allowed to place live-money orders.",
            "Pitcher-aware F2 currently uses pitcher identity/state and pitch-count fatigue, not ERA/FIP or bullpen quality; those belong in F3 only if F2 improves holdout behavior.",
        ],
    }
    Path("edge_v16_strategy_f_results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run(int(os.environ.get("EDGE_DAYS", "60")))
