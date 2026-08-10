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

ENTRY_FRICTION_CENTS = 1.0
EXIT_FRICTION_CENTS = 0.5
BASE_STAKE = 1.0


def grouped_by_game(rows):
    out = defaultdict(list)
    for r in rows:
        out[r["game_pk"]].append(r)
    for vals in out.values():
        vals.sort(key=lambda x: x["ts"])
    return out


def first_quotes(game_rows):
    first = {}
    for r in game_rows:
        first.setdefault(r["side"], r)
    if len(first) != 2:
        return None
    sides = list(first)
    return first[sides[0]], first[sides[1]]


def entry_contracts(dollars, ask_cents):
    px = min(99.0, float(ask_cents) + ENTRY_FRICTION_CENTS)
    if px <= 0:
        return 0.0, px
    return dollars * 100.0 / px, px


def exit_value(contracts, bid_cents):
    px = max(0.0, float(bid_cents) - EXIT_FRICTION_CENTS)
    return contracts * px / 100.0, px


def settlement_value(contracts, won):
    return contracts if won else 0.0


def replay_game(game_rows, cfg):
    fq = first_quotes(game_rows)
    if not fq:
        return None
    a0, b0 = fq
    favorite0 = a0 if a0["pregame_side"] >= b0["pregame_side"] else b0
    dog0 = b0 if favorite0 is a0 else a0
    if favorite0["pregame_side"] < 50:
        return None

    positions = []
    total_cost = 0.0

    def buy(row, dollars, label):
        nonlocal total_cost
        contracts, effective_px = entry_contracts(dollars, row["ask"])
        if contracts <= 0:
            return None
        total_cost += dollars
        p = {"side": row["side"], "contracts": contracts, "cost": dollars, "entry_px": effective_px, "label": label, "won": row["won"], "closed": False, "close_value": 0.0}
        positions.append(p)
        return p

    if cfg["start_mode"] == "DUAL":
        buy(favorite0, BASE_STAKE, "START_FAVORITE")
        buy(dog0, BASE_STAKE, "START_DOG")
    else:
        buy(favorite0, BASE_STAKE, "START_FAVORITE")

    latest = {favorite0["side"]: favorite0, dog0["side"]: dog0}
    hedge = None
    trigger_row = None
    hedge_side = None

    for r in game_rows:
        latest[r["side"]] = r
        fav_now = latest.get(favorite0["side"])
        dog_now = latest.get(dog0["side"])
        if not fav_now or not dog_now:
            continue

        if hedge is None:
            # User hypothesis: favorite appreciates sharply, then add the crushed opposite side.
            if int(fav_now.get("inning") or 0) <= cfg["max_trigger_inning"] and float(fav_now["ask"]) >= cfg["leader_trigger"]:
                hedge_dollars = BASE_STAKE * cfg["hedge_mult"]
                hedge = buy(dog_now, hedge_dollars, "DYNAMIC_HEDGE")
                trigger_row = fav_now
                hedge_side = dog_now["side"]
                continue
        elif hedge and not hedge["closed"] and cfg["exit_target_cents"] is not None:
            q = latest.get(hedge_side)
            if q is not None:
                effective_bid = max(0.0, float(q["bid"]) - EXIT_FRICTION_CENTS)
                if effective_bid >= hedge["entry_px"] + cfg["exit_target_cents"]:
                    value, _ = exit_value(hedge["contracts"], q["bid"])
                    hedge["closed"] = True
                    hedge["close_value"] = value
                    hedge["exit_ts"] = q["ts"]

    if hedge is None:
        return None

    final_value = 0.0
    for p in positions:
        if p["closed"]:
            final_value += p["close_value"]
        else:
            final_value += settlement_value(p["contracts"], p["won"])

    pnl = final_value - total_cost
    roi = 100.0 * pnl / total_cost if total_cost else 0.0
    return {
        "date": favorite0["date"],
        "game_pk": favorite0["game_pk"],
        "favorite": favorite0["side"],
        "dog": dog0["side"],
        "favorite_pregame": favorite0["pregame_side"],
        "trigger_price": trigger_row["ask"] if trigger_row else None,
        "trigger_inning": trigger_row["inning"] if trigger_row else None,
        "total_cost": round(total_cost, 4),
        "final_value": round(final_value, 4),
        "pnl": round(pnl, 4),
        "roi_pct": round(roi, 2),
        "favorite_won": bool(favorite0["won"]),
        "hedge_closed_early": bool(hedge and hedge["closed"]),
        "hedge_entry_px": round(hedge["entry_px"], 2) if hedge else None,
        "config": cfg,
    }


def stats(replays):
    if not replays:
        return {"games": 0, "roi_pct": None}
    pnl = sum(r["pnl"] for r in replays)
    cost = sum(r["total_cost"] for r in replays)
    wins = [r for r in replays if r["pnl"] > 0]
    equity = peak = max_dd = 0.0
    for r in replays:
        equity += r["pnl"]
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return {
        "games": len(replays),
        "total_cost_units": round(cost, 2),
        "total_pnl_units": round(pnl, 3),
        "roi_pct": round(100 * pnl / cost, 2) if cost else None,
        "positive_game_pct": round(100 * len(wins) / len(replays), 2),
        "avg_pnl_units": round(pnl / len(replays), 4),
        "avg_game_roi_pct": round(sum(r["roi_pct"] for r in replays) / len(replays), 2),
        "max_drawdown_units": round(max_dd, 3),
        "hedge_early_exit_pct": round(100 * sum(r["hedge_closed_early"] for r in replays) / len(replays), 2),
    }


def build_configs():
    configs = []
    for start_mode, trigger, mult, target, max_inning in product(
        ["DUAL", "FAVORITE_ONLY"],
        [70, 75, 80, 85],
        [0.25, 0.5, 1.0],
        [None, 5, 10, 15],
        [4, 5, 6],
    ):
        configs.append({
            "start_mode": start_mode,
            "leader_trigger": trigger,
            "hedge_mult": mult,
            "exit_target_cents": target,
            "max_trigger_inning": max_inning,
        })
    return configs


def evaluate(rows, cfg):
    reps = []
    for game_rows in grouped_by_game(rows).values():
        r = replay_game(game_rows, cfg)
        if r:
            reps.append(r)
    reps.sort(key=lambda x: (x["date"], x["game_pk"]))
    return reps


def run(days=120):
    observation_source.markets_for_day = archive.combined_markets_for_day
    start, end, obs, coverage = observation_source.corrected_build_observations(days)
    dates = sorted({r["date"] for r in obs})
    n = len(dates)
    c1, c2 = max(1, int(n * .50)), max(2, int(n * .75))
    dev_dates = set(dates[:c1])
    val_dates = set(dates[c1:c2])
    hold_dates = set(dates[c2:])
    dev = [r for r in obs if r["date"] in dev_dates]
    val = [r for r in obs if r["date"] in val_dates]
    hold = [r for r in obs if r["date"] in hold_dates]

    # Fit EDGE on development only; preserved for future model-aware hedge filters and leakage discipline.
    params = fit(dev)
    for rows in (dev, val, hold):
        apply_model(rows, params)

    candidates = []
    configs = build_configs()
    for cfg in configs:
        dr, vr = evaluate(dev, cfg), evaluate(val, cfg)
        ds, vs = stats(dr), stats(vr)
        if ds["games"] < 20 or vs["games"] < 10:
            continue
        if ds["roi_pct"] is None or vs["roi_pct"] is None or ds["roi_pct"] <= 0 or vs["roi_pct"] <= 0:
            continue
        score = min(ds["roi_pct"], vs["roi_pct"]) + 0.20 * ((ds["roi_pct"] + vs["roi_pct"]) / 2)
        candidates.append({"score": round(score, 4), "config": cfg, "development": ds, "validation": vs})

    candidates.sort(key=lambda x: (x["score"], x["validation"]["games"]), reverse=True)
    winner = candidates[0] if candidates else None
    hold_replays = evaluate(hold, winner["config"]) if winner else []
    hold_stats = stats(hold_replays) if winner else None

    # Benchmarks on the exact same holdout games/config trigger.
    benchmark = None
    if winner:
        cfg = dict(winner["config"])
        dual_cfg = {**cfg, "start_mode": "DUAL"}
        single_cfg = {**cfg, "start_mode": "FAVORITE_ONLY"}
        benchmark = {
            "same_trigger_dual": stats(evaluate(hold, dual_cfg)),
            "same_trigger_favorite_only": stats(evaluate(hold, single_cfg)),
        }

    result = {
        "version": "EDGE-MLB-v1.4-strategy-e-dynamic-hedge",
        "hypothesis": "When the pregame favorite appreciates sharply, the opposite side may become attractive enough to hedge or DCA; compare dual-start versus capital-efficient favorite-only starts and optional hedge rebound exits.",
        "period": {"start": str(start), "end": str(end), "requested_days": days},
        "coverage": coverage,
        "split": {
            "method": "50% development / 25% validation / 25% final untouched holdout",
            "development_dates": [min(dev_dates, default=None), max(dev_dates, default=None)],
            "validation_dates": [min(val_dates, default=None), max(val_dates, default=None)],
            "holdout_dates": [min(hold_dates, default=None), max(hold_dates, default=None)],
        },
        "search": {"configs_tested": len(configs), "robust_positive_candidates": len(candidates)},
        "selected_strategy": winner,
        "final_untouched_result": hold_stats,
        "holdout_same_trigger_benchmarks": benchmark,
        "top_candidates_before_holdout": candidates[:25],
        "guardrails": [
            "Final holdout is not used to select the hedge configuration.",
            "Historical simulation is not proof of future profitability.",
            "Uses observed one-minute bid/ask history with +1c entry and -0.5c exit friction assumptions.",
            "No live-money execution is enabled.",
        ],
    }
    Path("edge_v14_strategy_e_results.json").write_text(json.dumps(result, indent=2))
    Path("edge_v14_strategy_e_holdout_replays.json").write_text(json.dumps(hold_replays, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run(int(os.environ.get("EDGE_DAYS", "120")))
