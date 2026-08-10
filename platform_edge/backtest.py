from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any, Iterable

from .models import EdgeHistoricalSnapshot


def _run_market_strategy(rows: Iterable[EdgeHistoricalSnapshot], minimum_edge_pct: float, fee_bps: float, risk_cents: int) -> dict[str, Any]:
    opportunities = wins = 0
    pnl = 0.0
    equity = peak = max_drawdown = 0.0
    losing = max_losing = 0
    brier_values: list[float] = []
    for row in rows:
        if row.yes_ask_cents is None or row.model_probability_bps is None or row.market_result not in {"YES", "NO"}:
            continue
        if row.yes_bid_cents is not None and row.yes_ask_cents - row.yes_bid_cents > 3:
            continue
        model = row.model_probability_bps / 100.0
        market = float(row.yes_ask_cents)
        outcome = 1.0 if row.market_result == "YES" else 0.0
        brier_values.append((model / 100.0 - outcome) ** 2)
        if model - market < minimum_edge_pct or not 0 < market < 100:
            continue
        opportunities += 1
        wins += int(outcome == 1.0)
        contracts = risk_cents / market
        gross = contracts * ((outcome * 100.0) - market)
        fee = risk_cents * fee_bps / 10000.0
        trade_pnl = gross - fee
        pnl += trade_pnl
        equity += trade_pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if trade_pnl < 0:
            losing += 1
            max_losing = max(max_losing, losing)
        else:
            losing = 0
    return {
        "minimum_edge_pct": minimum_edge_pct,
        "samples": len(list(rows)) if not isinstance(rows, list) else len(rows),
        "opportunities": opportunities,
        "wins": wins,
        "win_rate_pct": round(wins / opportunities * 100, 3) if opportunities else 0.0,
        "total_risk_cents": opportunities * risk_cents,
        "total_pnl_cents": round(pnl, 3),
        "roi_pct": round(pnl / (opportunities * risk_cents) * 100, 3) if opportunities else 0.0,
        "avg_pnl_cents": round(pnl / opportunities, 3) if opportunities else 0.0,
        "max_drawdown_cents": round(max_drawdown, 3),
        "max_losing_streak": max_losing,
        "brier_score": round(sum(brier_values) / len(brier_values), 6) if brier_values else None,
    }


def _bucket_rows(rows: list[EdgeHistoricalSnapshot]) -> list[dict[str, Any]]:
    buckets: dict[str, list[EdgeHistoricalSnapshot]] = defaultdict(list)
    for row in rows:
        if row.market_result not in {"YES", "NO"}:
            continue
        diff = int(row.away_score) - int(row.home_score)
        if row.side_code == row.home_code:
            diff = -diff
        if diff >= 0:
            continue
        deficit = abs(diff)
        inning = int(row.inning or 0)
        half = (row.inning_half or "").upper()
        remaining = max(0, 9 - inning + (1 if half == "TOP" else 0))
        run_bucket = "down_1" if deficit == 1 else "down_2" if deficit == 2 else "down_3_plus"
        remaining_bucket = "4_plus" if remaining >= 4 else "3" if remaining == 3 else "2" if remaining == 2 else "1"
        buckets[f"{run_bucket}|{remaining_bucket}_innings_remaining"].append(row)
    result = []
    for key, items in sorted(buckets.items()):
        wins = sum(1 for row in items if row.market_result == "YES")
        prices = [row.yes_close_cents for row in items if row.yes_close_cents is not None]
        result.append({
            "bucket": key,
            "samples": len(items),
            "wins": wins,
            "actual_win_rate_pct": round(wins / len(items) * 100, 3) if items else 0.0,
            "average_market_price_pct": round(sum(prices) / len(prices), 3) if prices else None,
        })
    return result


def run_mlb_backtest(start: datetime | None = None, end: datetime | None = None, fee_bps: float = 0.0, risk_cents: int = 100) -> dict[str, Any]:
    qs = EdgeHistoricalSnapshot.objects.all().order_by("observed_at", "id")
    if start:
        qs = qs.filter(observed_at__gte=start)
    if end:
        qs = qs.filter(observed_at__lt=end)
    rows = list(qs)
    strategies = [_run_market_strategy(rows, threshold, fee_bps, risk_cents) for threshold in (5.0, 8.0, 10.0)]
    return {
        "dataset": {"samples": len(rows), "start": start.isoformat() if start else None, "end": end.isoformat() if end else None},
        "strategies": strategies,
        "comeback_buckets": _bucket_rows(rows),
        "cost_assumption": {"fee_bps": fee_bps, "risk_cents_per_trade": risk_cents, "spread_filter_cents": 3},
        "status": "research_only",
        "note": "This is historical analysis, not a profitability guarantee. Use held-out dates before treating a rule as validated.",
    }
