from __future__ import annotations

import bisect
import json
import os
from collections import defaultdict
from itertools import product
from pathlib import Path

import edge_v16_strategy_f as f

THRESHOLDS = (5, 8, 10, 12)
MIN_VALIDATION_TRADES = 40


def advanced_timeline(game_pk):
    payload = f.get_json(f.MLB_FEED.format(game_pk=game_pk))
    plays = payload.get("liveData", {}).get("plays", {}).get("allPlays", [])
    rows = []
    pitchers_seen = {"home": [], "away": []}
    starter_id = {}
    stats = defaultdict(lambda: {"pitches": 0, "bf": 0, "hits": 0, "walks_hbp": 0, "strikeouts": 0})

    for play in plays:
        about = play.get("about") or {}
        events = play.get("playEvents") or []
        if not events or not about.get("isComplete"):
            continue
        when = f.dt(events[-1].get("endTime"))
        if not when:
            continue
        matchup = play.get("matchup") or {}
        pitcher = matchup.get("pitcher") or {}
        pid = pitcher.get("id")
        if not pid:
            continue
        half = str(about.get("halfInning") or "").lower()
        defense = "home" if half == "top" else "away"
        if pid not in pitchers_seen[defense]:
            pitchers_seen[defense].append(pid)
        starter_id.setdefault(defense, pid)

        st = stats[pid]
        st["pitches"] += sum(1 for ev in events if ev.get("isPitch"))
        st["bf"] += 1
        event_type = str((play.get("result") or {}).get("eventType") or "").lower()
        if event_type in {"single", "double", "triple", "home_run"}:
            st["hits"] += 1
        if event_type in {"walk", "intent_walk", "hit_by_pitch"}:
            st["walks_hbp"] += 1
        if event_type in {"strikeout", "strikeout_double_play"}:
            st["strikeouts"] += 1

        occupied = set()
        for runner in play.get("runners") or []:
            movement = runner.get("movement") or {}
            details = runner.get("details") or {}
            if details.get("isOut") or movement.get("isOut"):
                continue
            end = movement.get("end")
            if end in ("1B", "2B", "3B"):
                occupied.add(end)

        bf = max(1, st["bf"])
        rows.append({
            "ts": when.timestamp(),
            "defense": defense,
            "pitcher_id": pid,
            "pitcher_name": pitcher.get("fullName"),
            "pitch_count": st["pitches"],
            "starter_active": starter_id[defense] == pid,
            "batters_faced": st["bf"],
            "hits_allowed": st["hits"],
            "walks_hbp": st["walks_hbp"],
            "strikeouts": st["strikeouts"],
            "trouble_rate": (st["hits"] + st["walks_hbp"]) / bf,
            "strikeout_rate": st["strikeouts"] / bf,
            "relievers_used": max(0, len(pitchers_seen[defense]) - 1),
            "runners_on_base": len(occupied),
        })
    return sorted(rows, key=lambda x: x["ts"])


def enrich_advanced(obs):
    by_game = defaultdict(list)
    for row in obs:
        by_game[row["game_pk"]].append(row)
    coverage = {"games_requested": len(by_game), "games_enriched": 0, "observations_enriched": 0, "errors": []}
    for game_pk, game_rows in by_game.items():
        try:
            timeline = advanced_timeline(game_pk)
        except Exception as exc:
            coverage["errors"].append({"game_pk": game_pk, "error": str(exc)})
            continue
        if not timeline:
            continue
        coverage["games_enriched"] += 1
        times = [x["ts"] for x in timeline]
        for row in game_rows:
            idx = bisect.bisect_right(times, row["ts"]) - 1
            if idx < 0:
                continue
            state = timeline[idx]
            defensive_team = row["home"] if state["defense"] == "home" else row["away"]
            sign = 1.0 if row["side"] == defensive_team else -1.0
            for key in ("pitcher_id", "pitcher_name", "pitch_count", "starter_active", "batters_faced", "hits_allowed", "walks_hbp", "strikeouts", "trouble_rate", "strikeout_rate", "relievers_used", "runners_on_base"):
                row[key] = state[key]
            row["pitching_sign"] = sign
            coverage["observations_enriched"] += 1
    return coverage


def cfg_only(cfg):
    return {k: cfg[k] for k in ("base_run", "late_run", "starter_coef", "pitch_coef")}


def fair_f3(row, cfg):
    base_p = f.fair_side(row, **cfg_only(cfg))
    logit = f.logit(base_p)
    sign = float(row.get("pitching_sign") or 0.0)
    if sign:
        trouble = float(row.get("trouble_rate") or 0.0)
        k_rate = float(row.get("strikeout_rate") or 0.0)
        relievers = float(row.get("relievers_used") or 0.0)
        runners = float(row.get("runners_on_base") or 0.0)
        logit -= sign * cfg["trouble_coef"] * trouble
        logit += sign * cfg["k_coef"] * (k_rate - 0.22)
        logit -= sign * cfg["bullpen_coef"] * relievers
        logit -= sign * cfg["runner_coef"] * runners
    return f.sigmoid(logit)


def brier_f3(rows, cfg):
    vals = []
    for row in f.unique_fit_rows(rows):
        p = fair_f3(row, cfg)
        y = 1.0 if row["won"] else 0.0
        vals.append((p - y) ** 2)
    return sum(vals) / len(vals) if vals else 1.0


def fit_f3(rows, f2_cfg):
    best = None
    for trouble, kcoef, bullpen, runner in product(
        (0.0, 0.15, 0.30, 0.45),
        (0.0, 0.15, 0.30),
        (0.0, 0.05, 0.10),
        (0.0, 0.10, 0.20, 0.30),
    ):
        cfg = {
            **cfg_only(f2_cfg),
            "trouble_coef": trouble,
            "k_coef": kcoef,
            "bullpen_coef": bullpen,
            "runner_coef": runner,
        }
        score = brier_f3(rows, cfg)
        if best is None or score < best[0]:
            best = (score, cfg)
    score, cfg = best
    return {**cfg, "train_brier": round(score, 6)}


def replay(rows, model, cfg, threshold):
    first = {}
    for row in sorted(rows, key=lambda x: x["ts"]):
        ask = float(row["ask"])
        p = (fair_f3(row, cfg) if model == "F3" else f.fair_side(row, **cfg_only(cfg))) * 100.0
        edge = p - ask
        if edge < threshold or ask + f.ENTRY_FRICTION_CENTS >= 100:
            continue
        first.setdefault(row["game_pk"], {**row, "model_pct": p, "edge_pct": edge})
    trades = list(first.values())
    equity = peak = 0.0
    max_dd = 0.0
    wins = 0
    pnl = []
    for row in trades:
        entry = min(99.0, float(row["ask"]) + f.ENTRY_FRICTION_CENTS)
        trade_pnl = (100.0 / entry - 1.0) if row["won"] else -1.0
        pnl.append(trade_pnl)
        wins += int(row["won"])
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


def validation_pack(rows, model, cfg):
    return {str(t): replay(rows, model, cfg, t) for t in THRESHOLDS}


def select_threshold(validation):
    eligible = [(int(t), stats) for t, stats in validation.items() if stats["trades"] >= MIN_VALIDATION_TRADES]
    if not eligible:
        eligible = [(int(t), stats) for t, stats in validation.items() if stats["trades"] > 0]
    eligible.sort(key=lambda item: (item[1]["roi_pct"] if item[1]["roi_pct"] is not None else -9999, item[1]["trades"]), reverse=True)
    return eligible[0][0] if eligible else None


def model_result(name, model, cfg, dev, val, hold):
    val_thresholds = validation_pack(val, model, cfg)
    selected = select_threshold(val_thresholds)
    brier_fn = brier_f3 if model == "F3" else lambda rows, c: f.brier(rows, cfg_only(c))
    return {
        "name": name,
        "fit": cfg,
        "development_brier": round(brier_fn(dev, cfg), 6),
        "validation_brier": round(brier_fn(val, cfg), 6),
        "validation_thresholds": val_thresholds,
        "selected_threshold": selected,
        "holdout_brier": round(brier_fn(hold, cfg), 6),
        "holdout_selected_only": replay(hold, model, cfg, selected) if selected is not None else None,
    }


def run(days=60):
    f.source.markets_for_day = f.archive.combined_markets_for_day
    start, end, obs, coverage = f.source.corrected_build_observations(days)
    pitcher_coverage = f.enrich_pitchers(obs)
    advanced_coverage = enrich_advanced(obs)

    dates = sorted({r["date"] for r in obs})
    c1 = max(1, int(len(dates) * 0.50))
    c2 = max(c1 + 1, int(len(dates) * 0.75))
    dev_dates, val_dates, hold_dates = set(dates[:c1]), set(dates[c1:c2]), set(dates[c2:])
    dev = [r for r in obs if r["date"] in dev_dates]
    val = [r for r in obs if r["date"] in val_dates]
    hold = [r for r in obs if r["date"] in hold_dates]

    f1 = f.fit(dev, pitcher_aware=False)
    f2 = f.fit(dev, pitcher_aware=True)
    f3 = fit_f3(dev, f2)

    result = {
        "version": "EDGE-MLB-v1.7-Strategy-F3",
        "period": [str(start), str(end)],
        "coverage": coverage,
        "pitcher_coverage": pitcher_coverage,
        "advanced_coverage": advanced_coverage,
        "split": "50% development / 25% validation / 25% untouched holdout",
        "selection_rule": "Model coefficients fit on development only. Entry threshold chosen by validation ROI with >=40 trades when available. Holdout is evaluated only at the validation-selected threshold.",
        "models": {
            "F1_GAME_STATE": model_result("F1 game-state", "F1", f1, dev, val, hold),
            "F2_PITCHER_AWARE": model_result("F2 pitch-count/fatigue", "F2", f2, dev, val, hold),
            "F3_BASEBALL_CONTEXT": model_result("F3 pitcher performance + base pressure + bullpen usage", "F3", f3, dev, val, hold),
        },
        "f3_features": [
            "pregame probability", "score", "inning", "half", "outs", "current pitcher", "starter active",
            "pitch count", "batters faced", "hits/walks/HBP pressure", "strikeout rate", "relievers already used", "runners on base",
        ],
        "guardrails": [
            "Research only; no live-money orders.",
            "One simulated entry per game per model/threshold.",
            "Entry friction +1.5 cents.",
            "No holdout threshold optimization.",
            "A/B/E1/E2 frozen experiment is untouched.",
        ],
    }
    Path("edge_v17_strategy_f3_results.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run(int(os.environ.get("EDGE_DAYS", "60")))
