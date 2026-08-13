from __future__ import annotations

from collections import defaultdict

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import EdgeAuditEvent, EdgePaperTrade
from .portfolio_views import _strategy_boards

BANKROLL_CENTS_PER_STRATEGY = 10000

STRATEGY_REGISTRY = {
    "A": {
        "name": "Strategy A",
        "family": "MLB comeback reversion",
        "live_adapter": True,
        "status": "LIVE_PAPER",
        "note": "Frozen production paper rule.",
    },
    "B": {
        "name": "Strategy B",
        "family": "MLB coin-flip comeback",
        "live_adapter": True,
        "status": "LIVE_PAPER",
        "note": "Frozen production paper rule.",
    },
    "E1": {
        "name": "E1",
        "family": "MLB E-family candidate",
        "live_adapter": False,
        "status": "RULE_RECOVERY_REQUIRED",
        "note": "Reserved for the previously tested E1 rule. The exact frozen thresholds are not present in the production repository, so EDGE will not invent them.",
    },
    "E2": {
        "name": "E2 PRIME",
        "family": "MLB E-family candidate",
        "live_adapter": False,
        "status": "RULE_RECOVERY_REQUIRED",
        "note": "Reserved for the previously tested E2 PRIME rule. Exact frozen thresholds must be restored before live paper execution begins.",
    },
}


def _strategy_code(trade):
    if not trade.signal:
        return None
    event_key = str(trade.signal.event_key or "")
    parts = event_key.split(":")
    if len(parts) >= 2 and parts[0] == "PORTFOLIO":
        return parts[1]
    signal = str(trade.signal.signal or "")
    if signal.startswith("STRATEGY_"):
        return signal.replace("STRATEGY_", "", 1)
    return None


def _historical_metadata():
    out = {}
    try:
        boards = _strategy_boards()
    except Exception:
        boards = {}
    for code, board in boards.items():
        strategy = board.get("strategy") or {}
        out[code] = {
            "historical_result": strategy.get("historical_result"),
            "rule": strategy.get("rule"),
        }
    return out


def _summary_for(code, trades, registry, historical):
    rows = [trade for trade in trades if _strategy_code(trade) == code]
    closed = [trade for trade in rows if trade.status in {"EXITED", "SETTLED"}]
    open_rows = [trade for trade in rows if trade.status == "OPEN"]
    risk_total = sum(int(trade.risk_cents or 0) for trade in closed)
    realized = sum(int(trade.pnl_cents or 0) for trade in closed)
    wins = sum(1 for trade in closed if int(trade.pnl_cents or 0) > 0)
    losses = sum(1 for trade in closed if int(trade.pnl_cents or 0) < 0)
    flats = len(closed) - wins - losses
    roi = (100.0 * realized / risk_total) if risk_total else None
    win_rate = (100.0 * wins / len(closed)) if closed else None
    open_risk = sum(int(trade.risk_cents or 0) for trade in open_rows)
    bankroll = BANKROLL_CENTS_PER_STRATEGY + realized
    return {
        "code": code,
        **registry,
        "rank_eligible": bool(registry.get("live_adapter") and len(closed) > 0),
        "paper_bankroll_start_cents": BANKROLL_CENTS_PER_STRATEGY,
        "paper_equity_cents": bankroll,
        "realized_pnl_cents": realized,
        "roi_pct": round(roi, 2) if roi is not None else None,
        "trades": len(rows),
        "closed_trades": len(closed),
        "open_trades": len(open_rows),
        "open_risk_cents": open_risk,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "positive_trade_rate_pct": round(win_rate, 2) if win_rate is not None else None,
        "historical": historical.get(code),
        "recent_trades": [
            {
                "id": trade.id,
                "status": trade.status,
                "side": trade.side,
                "risk_cents": trade.risk_cents,
                "entry_price_cents": trade.entry_price_cents,
                "exit_price_cents": trade.exit_price_cents,
                "pnl_cents": trade.pnl_cents,
                "created_at": trade.created_at,
                "closed_at": trade.closed_at,
                "matchup": trade.signal.matchup if trade.signal else None,
                "game_state": trade.signal.game_state if trade.signal else None,
            }
            for trade in rows[:10]
        ],
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def strategy_scoreboard(request):
    trades = list(
        EdgePaperTrade.objects.filter(user=request.user)
        .select_related("signal")
        .order_by("-created_at")[:500]
    )
    historical = _historical_metadata()
    strategies = [
        _summary_for(code, trades, registry, historical)
        for code, registry in STRATEGY_REGISTRY.items()
    ]
    ranked = [row for row in strategies if row["rank_eligible"]]
    ranked.sort(key=lambda row: (row["roi_pct"] if row["roi_pct"] is not None else -9999, row["closed_trades"]), reverse=True)
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index

    experiment_start = EdgeAuditEvent.objects.filter(
        user=request.user,
        event_type="PORTFOLIO_SERVER_TICK",
    ).order_by("created_at").first()

    return Response({
        "mode": "paper_only",
        "live_money_enabled": False,
        "experiment_start_at": experiment_start.created_at if experiment_start else None,
        "paper_bankroll_per_strategy_cents": BANKROLL_CENTS_PER_STRATEGY,
        "ranking_method": "realized ROI first; closed-trade count breaks ties",
        "strategies": strategies,
        "leader": ranked[0]["code"] if ranked else None,
        "research_note": "Each strategy is evaluated independently. E1/E2 are registered but intentionally cannot trade until their exact previously frozen rule definitions are restored.",
    })
