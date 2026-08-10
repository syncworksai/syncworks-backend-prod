from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

import edge_v08b_reversion as observation_source
import edge_v10b_strategy_discovery as archive
from edge_v07_pregame_holdout import fit
from edge_v09_focused_reversion import apply_model, executable_bid

ENTRY_FRICTION = 1.0
EXIT_FRICTION = 0.5
DAILY_RISK_PCT = 1.0
PER_GAME_RISK_PCT = 0.50
PER_ENTRY_RISK_PCT = 0.25
COOLDOWN_MINUTES = 5


def qualifies_a(r):
    return (
        55 <= r["pregame_side"] < 65
        and r["trailing"]
        and r["deficit"] in (1, 2)
        and 4 <= r["inning"] <= 6
        and r["drop_from_pregame"] >= 18
        and r["edge_v09"] >= 5
    )


def qualifies_b(r):
    batting = (
        (r["side"] == r["away"] and str(r["half"]).lower() == "top")
        or (r["side"] == r["home"] and str(r["half"]).lower() == "bottom")
    )
    return (
        45 <= r["pregame_side"] < 55
        and r["trailing"]
        and r["deficit"] == 1
        and 4 <= r["inning"] <= 6
        and r["drop_from_pregame"] >= 10
        and r["edge_v09"] >= 3
        and batting
    )


def strategy_for(r):
    if qualifies_a(r):
        return "A", 20
    if qualifies_b(r):
        return "B", 30
    return None, None


def fingerprint(r, strategy):
    return (
        strategy,
        r["ticker"],
        r["game_pk"],
        r["inning"],
        str(r["half"]).lower(),
        r["deficit"],
        r["away_score"],
        r["home_score"],
    )


def group_rows(rows):
    out = defaultdict(list)
    for r in rows:
        out[r["ticker"]].append(r)
    for vals in out.values():
        vals.sort(key=lambda x: x["ts"])
    return out


def exit_row(series, entry_ts, hold_minutes):
    target = entry_ts + hold_minutes * 60
    future = [r for r in series if r["ts"] > entry_ts]
    if not future:
        return None
    return next((r for r in future if r["ts"] >= target), future[-1])


def trade_from_entry(r, strategy, hold_minutes, grouped):
    series = grouped[r["ticker"]]
    out = exit_row(series, r["ts"], hold_minutes)
    if out is None:
        return None
    entry_px = min(99.0, float(r["ask"]) + ENTRY_FRICTION)
    exit_px = max(0.0, float(out["bid"]) - EXIT_FRICTION)
    if entry_px <= 0:
        return None
    roi = 100 * (exit_px / entry_px - 1)
    return {
        "date": r["date"], "game_pk": r["game_pk"], "ticker": r["ticker"], "side": r["side"],
        "strategy": strategy, "entry_ts": r["ts"], "exit_ts": out["ts"],
        "hold_minutes": hold_minutes, "entry_px": round(entry_px, 2), "exit_px": round(exit_px, 2),
        "roi_pct": round(roi, 2), "fingerprint": fingerprint(r, strategy),
        "inning": r["inning"], "half": r["half"], "deficit": r["deficit"],
        "pregame_side": r["pregame_side"], "drop": r["drop_from_pregame"], "edge": r["edge_v09"],
    }


def candidate_trades(rows):
    grouped = group_rows(rows)
    candidates = []
    seen = set()
    for r in sorted(rows, key=lambda x: x["ts"]):
        strategy, hold = strategy_for(r)
        if not strategy:
            continue
        fp = fingerprint(r, strategy)
        if fp in seen:
            continue
        seen.add(fp)
        t = trade_from_entry(r, strategy, hold, grouped)
        if t:
            candidates.append(t)
    candidates.sort(key=lambda x: x["entry_ts"])
    return candidates


def simulate(candidates, multi_entry):
    daily_used = defaultdict(float)
    game_used = defaultdict(float)
    game_entry_count = defaultdict(int)
    last_exit_by_ticker = {}
    used_fingerprints = set()
    accepted = []
    skips = defaultdict(int)

    for t in candidates:
        day = t["date"]
        game = t["game_pk"]
        ticker = t["ticker"]
        fp = tuple(t["fingerprint"])

        if not multi_entry and game_entry_count[game] >= 1:
            skips["one_entry_game_limit"] += 1
            continue
        if daily_used[day] + PER_ENTRY_RISK_PCT > DAILY_RISK_PCT + 1e-9:
            skips["daily_risk_cap"] += 1
            continue
        if game_used[game] + PER_ENTRY_RISK_PCT > PER_GAME_RISK_PCT + 1e-9:
            skips["game_risk_cap"] += 1
            continue
        if fp in used_fingerprints:
            skips["same_state"] += 1
            continue
        last_exit = last_exit_by_ticker.get(ticker)
        if last_exit is not None and t["entry_ts"] < last_exit + COOLDOWN_MINUTES * 60:
            skips["cooldown"] += 1
            continue
        # One open position per market: a new entry must occur after the prior position on that ticker exited.
        if last_exit is not None and t["entry_ts"] < last_exit:
            skips["market_already_open"] += 1
            continue

        daily_used[day] += PER_ENTRY_RISK_PCT
        game_used[game] += PER_ENTRY_RISK_PCT
        game_entry_count[game] += 1
        used_fingerprints.add(fp)
        last_exit_by_ticker[ticker] = t["exit_ts"]
        accepted.append({**t, "risk_pct_bankroll": PER_ENTRY_RISK_PCT, "pnl_pct_bankroll": PER_ENTRY_RISK_PCT * t["roi_pct"] / 100})

    return accepted, skips


def summarize(trades):
    if not trades:
        return {"trades": 0}
    by_game = defaultdict(list)
    by_day = defaultdict(float)
    equity = peak = max_dd = 0.0
    for t in trades:
        by_game[t["game_pk"]].append(t)
        by_day[t["date"]] += t["pnl_pct_bankroll"]
        equity += t["pnl_pct_bankroll"]
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    positive = [t for t in trades if t["roi_pct"] > 0]
    second_plus = [t for vals in by_game.values() for t in vals[1:]]
    return {
        "trades": len(trades),
        "games_traded": len(by_game),
        "games_with_reentry": sum(1 for v in by_game.values() if len(v) > 1),
        "avg_entries_per_game": round(len(trades) / len(by_game), 2),
        "positive_trade_pct": round(100 * len(positive) / len(trades), 2),
        "avg_trade_roi_pct": round(sum(t["roi_pct"] for t in trades) / len(trades), 2),
        "total_pnl_pct_bankroll": round(sum(t["pnl_pct_bankroll"] for t in trades), 3),
        "avg_daily_pnl_pct_bankroll": round(sum(by_day.values()) / len(by_day), 4),
        "max_drawdown_pct_bankroll": round(max_dd, 3),
        "second_plus_trades": len(second_plus),
        "second_plus_avg_roi_pct": round(sum(t["roi_pct"] for t in second_plus) / len(second_plus), 2) if second_plus else None,
        "second_plus_positive_pct": round(100 * sum(t["roi_pct"] > 0 for t in second_plus) / len(second_plus), 2) if second_plus else None,
        "strategy_breakdown": {
            code: {
                "trades": len([t for t in trades if t["strategy"] == code]),
                "avg_roi_pct": round(sum(t["roi_pct"] for t in trades if t["strategy"] == code) / max(1, len([t for t in trades if t["strategy"] == code])), 2),
            }
            for code in ("A", "B")
        },
    }


def run(days=120):
    observation_source.markets_for_day = archive.combined_markets_for_day
    start, end, obs, coverage = observation_source.corrected_build_observations(days)
    dates = sorted({r["date"] for r in obs})
    cut = max(1, int(len(dates) * 0.50))
    train_dates = set(dates[:cut])
    hold_dates = set(dates[cut:])
    train = [r for r in obs if r["date"] in train_dates]
    holdout = [r for r in obs if r["date"] in hold_dates]

    params = fit(train)
    apply_model(train, params)
    apply_model(holdout, params)

    candidates = candidate_trades(holdout)
    single, single_skips = simulate(candidates, multi_entry=False)
    multi, multi_skips = simulate(candidates, multi_entry=True)
    single_stats = summarize(single)
    multi_stats = summarize(multi)

    result = {
        "version": "EDGE-MLB-v1.3-strategy-d-game-reentry",
        "hypothesis": "Allow repeated A/B entries in the same MLB game only after exit, cooldown, and materially new state; compare with one-entry-per-game under fixed risk caps.",
        "period": {"start": str(start), "end": str(end), "requested_days": days},
        "coverage": coverage,
        "split": {
            "method": "first 50% dates fit model; final 50% untouched portfolio replay",
            "train_dates": [min(train_dates, default=None), max(train_dates, default=None)],
            "holdout_dates": [min(hold_dates, default=None), max(hold_dates, default=None)],
        },
        "risk_rules": {
            "daily_risk_cap_pct": DAILY_RISK_PCT,
            "per_game_risk_cap_pct": PER_GAME_RISK_PCT,
            "per_entry_risk_pct": PER_ENTRY_RISK_PCT,
            "cooldown_minutes": COOLDOWN_MINUTES,
            "averaging_down": False,
            "one_open_position_per_market": True,
            "new_state_required": True,
        },
        "candidate_state_events": len(candidates),
        "one_entry_per_game": single_stats,
        "multi_entry_game_state": multi_stats,
        "incremental": {
            "extra_trades": multi_stats.get("trades", 0) - single_stats.get("trades", 0),
            "pnl_change_pct_bankroll": round(multi_stats.get("total_pnl_pct_bankroll", 0) - single_stats.get("total_pnl_pct_bankroll", 0), 3),
            "drawdown_change_pct_bankroll": round(multi_stats.get("max_drawdown_pct_bankroll", 0) - single_stats.get("max_drawdown_pct_bankroll", 0), 3),
        },
        "skip_reasons": {"single": dict(single_skips), "multi": dict(multi_skips)},
        "recommendation": None,
        "guardrails": [
            "Historical simulation is not proof of future profitability.",
            "No live-money execution is enabled.",
            "A and B rules are frozen; this test changes sequencing/risk only.",
        ],
    }
    extra = result["incremental"]["pnl_change_pct_bankroll"]
    result["recommendation"] = "KEEP_MULTI_ENTRY_FOR_FORWARD_PAPER" if extra > 0 and multi_stats.get("second_plus_trades", 0) >= 10 else "KEEP_ONE_ENTRY_UNTIL_MORE_EVIDENCE"

    Path("edge_v13_strategy_d_results.json").write_text(json.dumps(result, indent=2))
    Path("edge_v13_strategy_d_multi_trades.json").write_text(json.dumps(multi, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    run(int(os.environ.get("EDGE_DAYS", "120")))
