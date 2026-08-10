from datetime import datetime, time

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .backtest import run_mlb_backtest
from .models import EdgeAuditEvent, EdgePaperTrade, EdgeSignal
from .research_model import get_mlb_research_board


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mlb_research_board(request):
    try:
        minimum_edge = float(request.query_params.get("minimum_edge") or 8)
    except (TypeError, ValueError):
        minimum_edge = 8.0
    minimum_edge = max(0.0, min(50.0, minimum_edge))
    target_date = request.query_params.get("date") or None
    board = get_mlb_research_board(target_date, minimum_edge)
    for item in board.get("signals", []):
        EdgeSignal.objects.create(
            user=request.user, sport=item["sport"], event_key=item["event_key"], matchup=item["matchup"],
            game_state=item.get("game_state") or "", side=item["side"], market_price_cents=item["market_price_cents"],
            model_probability_bps=int(round(item["model_probability_pct"] * 100)), edge_bps=int(round(item["edge_pct"] * 100)),
            opportunity_score=item["opportunity_score"], signal=item["signal"], max_entry_cents=None,
        )
    return Response(board)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mlb_backtest(request):
    start_date = _parse_date(request.query_params.get("start"))
    end_date = _parse_date(request.query_params.get("end"))
    start = timezone.make_aware(datetime.combine(start_date, time.min)) if start_date else None
    end = timezone.make_aware(datetime.combine(end_date, time.max)) if end_date else None
    try:
        fee_bps = max(0.0, min(500.0, float(request.query_params.get("fee_bps") or 0)))
        risk_cents = max(1, min(100000, int(request.query_params.get("risk_cents") or 100)))
    except (TypeError, ValueError):
        return Response({"detail": "Invalid fee_bps or risk_cents."}, status=400)
    result = run_mlb_backtest(start, end, fee_bps, risk_cents)
    result["requested_range"] = {"start": request.query_params.get("start"), "end": request.query_params.get("end")}
    return Response(result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def paper_simulate(request):
    signal_id = request.data.get("signal_id")
    risk_cents = int(request.data.get("risk_cents") or 100)
    if risk_cents <= 0:
        return Response({"detail": "risk_cents must be positive."}, status=400)
    signal = EdgeSignal.objects.filter(id=signal_id, user=request.user).first()
    if not signal:
        return Response({"detail": "Signal not found."}, status=404)
    if signal.market_price_cents <= 0 or signal.market_price_cents >= 100:
        return Response({"detail": "Signal price is not simulatable."}, status=400)
    trade = EdgePaperTrade.objects.create(user=request.user, signal=signal, side=signal.side, risk_cents=risk_cents, entry_price_cents=signal.market_price_cents, status="OPEN")
    EdgeAuditEvent.objects.create(user=request.user, event_type="PAPER_SIMULATION_OPENED", payload={"paper_trade_id": trade.id, "signal_id": signal.id, "risk_cents": risk_cents})
    return Response({"id": trade.id, "status": trade.status, "side": trade.side, "risk_cents": trade.risk_cents, "entry_price_cents": trade.entry_price_cents, "message": "Paper position created. No exchange order was placed."}, status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def paper_summary(request):
    trades = EdgePaperTrade.objects.filter(user=request.user).select_related("signal")[:100]
    return Response({"count": trades.count(), "trades": [{
        "id": t.id, "status": t.status, "side": t.side, "risk_cents": t.risk_cents,
        "entry_price_cents": t.entry_price_cents, "exit_price_cents": t.exit_price_cents,
        "pnl_cents": t.pnl_cents, "created_at": t.created_at, "closed_at": t.closed_at,
        "event_key": t.signal.event_key if t.signal else None,
    } for t in trades]})
