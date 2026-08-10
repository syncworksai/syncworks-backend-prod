from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import EdgeAuditEvent, EdgePaperTrade, EdgeSignal
from .strategy_a import get_strategy_a_live_board


def _trade_payload(trade):
    return {
        "id": trade.id,
        "status": trade.status,
        "side": trade.side,
        "risk_cents": trade.risk_cents,
        "entry_price_cents": trade.entry_price_cents,
        "exit_price_cents": trade.exit_price_cents,
        "pnl_cents": trade.pnl_cents,
        "created_at": trade.created_at,
        "closed_at": trade.closed_at,
        "event_key": trade.signal.event_key if trade.signal else None,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def strategy_a_live(request):
    board = get_strategy_a_live_board()
    recent = EdgePaperTrade.objects.filter(user=request.user).select_related("signal").order_by("-created_at")[:25]
    board["paper_trades"] = [_trade_payload(x) for x in recent]
    return Response(board)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def strategy_a_paper_tick(request):
    board = get_strategy_a_live_board()
    risk_cents = int(request.data.get("risk_cents") or 100)
    risk_cents = max(1, min(100000, risk_cents))
    current_by_ticker = {x.get("ticker"): x for x in board.get("signals", []) if x.get("ticker")}
    opened = []
    closed = []

    for item in board.get("qualifying_signals", []):
        event_key = f"STRATEGY_A:{item['ticker']}"
        existing = EdgePaperTrade.objects.filter(
            user=request.user,
            signal__event_key=event_key,
        ).exclude(status="SKIPPED").first()
        if existing:
            continue
        signal = EdgeSignal.objects.create(
            user=request.user,
            sport="MLB",
            event_key=event_key,
            matchup=item["matchup"],
            game_state=item.get("game_state") or "",
            side=item["side"],
            market_price_cents=item["current_ask_cents"],
            model_probability_bps=int(round(item["model_probability_pct"] * 100)),
            edge_bps=int(round(item["model_edge_pct"] * 100)),
            opportunity_score=max(0, min(100, int(round(50 + item["model_edge_pct"] * 3)))),
            signal="STRATEGY_A",
        )
        entry_price = min(99, int(item["current_ask_cents"]) + 1)
        trade = EdgePaperTrade.objects.create(
            user=request.user,
            signal=signal,
            side=item["side"],
            risk_cents=risk_cents,
            entry_price_cents=entry_price,
            status="OPEN",
        )
        EdgeAuditEvent.objects.create(
            user=request.user,
            event_type="STRATEGY_A_PAPER_OPEN",
            payload={"paper_trade_id": trade.id, "ticker": item["ticker"], "rule_version": "1.0-paper"},
        )
        opened.append(_trade_payload(trade))

    cutoff = timezone.now() - timedelta(minutes=20)
    open_trades = EdgePaperTrade.objects.filter(
        user=request.user,
        status="OPEN",
        signal__event_key__startswith="STRATEGY_A:",
        created_at__lte=cutoff,
    ).select_related("signal")
    for trade in open_trades:
        ticker = trade.signal.event_key.split("STRATEGY_A:", 1)[-1]
        current = current_by_ticker.get(ticker)
        if not current or current.get("current_bid_cents") is None:
            continue
        exit_price = max(0, int(current["current_bid_cents"]))
        effective_exit = max(0.0, exit_price - 0.5)
        pnl = round(trade.risk_cents * (effective_exit / trade.entry_price_cents - 1))
        trade.exit_price_cents = exit_price
        trade.pnl_cents = pnl
        trade.status = "EXITED"
        trade.closed_at = timezone.now()
        trade.save(update_fields=["exit_price_cents", "pnl_cents", "status", "closed_at"])
        EdgeAuditEvent.objects.create(
            user=request.user,
            event_type="STRATEGY_A_PAPER_EXIT",
            payload={"paper_trade_id": trade.id, "ticker": ticker, "exit_reason": "20_MINUTE_TIME_EXIT", "pnl_cents": pnl},
        )
        closed.append(_trade_payload(trade))

    recent = EdgePaperTrade.objects.filter(user=request.user, signal__event_key__startswith="STRATEGY_A:").select_related("signal").order_by("-created_at")[:50]
    return Response({
        "mode": "paper_only",
        "live_money_enabled": False,
        "opened": opened,
        "closed": closed,
        "paper_trades": [_trade_payload(x) for x in recent],
        "qualifying_now": board.get("qualifying_signals", []),
    })
