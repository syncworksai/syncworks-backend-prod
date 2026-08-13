from __future__ import annotations

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import EdgeAuditEvent, EdgePaperTrade
from .portfolio_views import _strategy_boards
from .strategy_e import FREEZE_VERSION, FROZEN_E_RULES

BANKROLL_CENTS_PER_STRATEGY = 10000

STRATEGY_REGISTRY = {
    "A": {"name": "Strategy A", "family": "MLB comeback reversion", "live_adapter": True, "status": "FROZEN_FORWARD_PAPER", "note": "Frozen rule. 55–65% pregame side, trailing 1–2, innings 4–6, >=18pt drop, >=5pt model edge, 20-minute exit."},
    "B": {"name": "Strategy B", "family": "MLB coin-flip comeback", "live_adapter": True, "status": "FROZEN_FORWARD_PAPER", "note": "Frozen rule. 45–55% pregame side, down 1, innings 4–6, >=10pt drop, >=3pt model edge, batting, 30-minute exit."},
    "E1": {"name": "E1", "family": "MLB favorite + dynamic opposite-side hedge", "live_adapter": True, "status": "FROZEN_FORWARD_PAPER", "note": "Frozen v1.5 rule. Start pregame favorite, trigger opposite-side hedge at 80c by inning 5, 25% hedge size, exit hedge on +5c rebound; favorite holds to settlement."},
    "E2": {"name": "E2 PRIME", "family": "MLB selective favorite + dynamic opposite-side hedge", "live_adapter": True, "status": "FROZEN_FORWARD_PAPER", "note": "Frozen v1.5 winner. Only 50–55% pregame favorites, trigger hedge at 87c by inning 5, 10% hedge size, exit hedge on +5c rebound; favorite holds to settlement."},
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
        out[code] = {"historical_result": strategy.get("historical_result"), "rule": strategy.get("rule")}
    for code, rule in FROZEN_E_RULES.items():
        out[code] = {"historical_result": rule.get("historical"), "rule": rule, "freeze_version": FREEZE_VERSION}
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
    positive_rate = (100.0 * wins / len(closed)) if closed else None
    open_risk = sum(int(trade.risk_cents or 0) for trade in open_rows)
    return {
        "code": code,
        **registry,
        "rules_frozen": True,
        "freeze_version": FREEZE_VERSION,
        "rank_eligible": bool(registry.get("live_adapter") and len(closed) > 0),
        "paper_bankroll_start_cents": BANKROLL_CENTS_PER_STRATEGY,
        "paper_equity_cents": BANKROLL_CENTS_PER_STRATEGY + realized,
        "realized_pnl_cents": realized,
        "roi_pct": round(roi, 2) if roi is not None else None,
        "trades": len(rows),
        "closed_trades": len(closed),
        "open_trades": len(open_rows),
        "open_risk_cents": open_risk,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "positive_trade_rate_pct": round(positive_rate, 2) if positive_rate is not None else None,
        "historical": historical.get(code),
        "recent_trades": [{
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
            "event_key": trade.signal.event_key if trade.signal else None,
        } for trade in rows[:10]],
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def strategy_scoreboard(request):
    frozen_start = EdgeAuditEvent.objects.filter(
        user=request.user,
        event_type="PORTFOLIO_SERVER_TICK",
        payload__rules_frozen=True,
    ).order_by("created_at").first()

    trade_query = EdgePaperTrade.objects.filter(user=request.user)
    if frozen_start:
        # The Strategy Race is a clean forward sample. Pre-freeze trades remain in the audit history but do not score.
        trade_query = trade_query.filter(created_at__gte=frozen_start.created_at)
    else:
        # Do not contaminate the race with legacy paper trades while waiting for the first frozen server tick.
        trade_query = trade_query.none()

    trades = list(trade_query.select_related("signal").order_by("-created_at")[:500])
    historical = _historical_metadata()
    strategies = [_summary_for(code, trades, registry, historical) for code, registry in STRATEGY_REGISTRY.items()]
    ranked = [row for row in strategies if row["rank_eligible"]]
    ranked.sort(key=lambda row: (row["roi_pct"] if row["roi_pct"] is not None else -9999, row["closed_trades"]), reverse=True)
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index

    return Response({
        "mode": "paper_only",
        "live_money_enabled": False,
        "rules_frozen": True,
        "freeze_version": FREEZE_VERSION,
        "experiment_start_at": frozen_start.created_at if frozen_start else None,
        "experiment_epoch_status": "ACTIVE" if frozen_start else "WAITING_FOR_FIRST_FROZEN_TICK",
        "paper_bankroll_per_strategy_cents": BANKROLL_CENTS_PER_STRATEGY,
        "daily_risk_cap_pct_per_strategy": 1.0,
        "ranking_method": "realized ROI first; closed-trade count breaks ties",
        "strategies": strategies,
        "leader": ranked[0]["code"] if ranked else None,
        "research_note": "A, B, E1 and E2 PRIME are frozen. The live race counts only trades opened at or after the first frozen server tick, so earlier paper activity cannot contaminate the comparison.",
    })
