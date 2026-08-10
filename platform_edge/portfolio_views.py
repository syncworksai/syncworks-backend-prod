from __future__ import annotations

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import EdgeAuditEvent, EdgePaperTrade, EdgeSignal
from .strategy_a import get_strategy_a_live_board
from .strategy_b import get_strategy_b_live_board

DAILY_RISK_PCT = 1.0
PER_GAME_RISK_PCT = 0.50
PER_ENTRY_RISK_PCT = 0.25
REENTRY_COOLDOWN_MINUTES = 5


def _today_start():
    now = timezone.localtime()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


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
        "strategy": trade.signal.signal if trade.signal else None,
    }


def _fingerprint(item, code):
    return ":".join([
        code,
        str(item.get("ticker") or ""),
        str(item.get("game_pk") or ""),
        str(item.get("inning") or ""),
        str(item.get("game_state") or ""),
        str(item.get("deficit") or 0),
    ])


def _strategy_boards():
    return {
        "A": get_strategy_a_live_board(),
        "B": get_strategy_b_live_board(),
    }


def _risk_snapshot(user, bankroll_cents):
    start = _today_start()
    trades = EdgePaperTrade.objects.filter(
        user=user,
        created_at__gte=start,
        signal__event_key__startswith="PORTFOLIO:",
    ).select_related("signal")
    daily_limit = max(1, round(bankroll_cents * DAILY_RISK_PCT / 100))
    used = trades.aggregate(total=Sum("risk_cents"))["total"] or 0
    open_risk = trades.filter(status="OPEN").aggregate(total=Sum("risk_cents"))["total"] or 0
    realized = trades.filter(status="EXITED").aggregate(total=Sum("pnl_cents"))["total"] or 0
    return {
        "bankroll_cents": bankroll_cents,
        "daily_limit_cents": daily_limit,
        "daily_used_cents": used,
        "daily_remaining_cents": max(0, daily_limit - used),
        "open_risk_cents": open_risk,
        "realized_pnl_cents": realized,
        "daily_risk_pct": DAILY_RISK_PCT,
        "per_game_risk_pct": PER_GAME_RISK_PCT,
        "per_entry_risk_pct": PER_ENTRY_RISK_PCT,
        "stop_new_entries": used >= daily_limit,
    }


def _game_risk_used(user, game_pk):
    start = _today_start()
    events = EdgeAuditEvent.objects.filter(
        user=user,
        event_type="PORTFOLIO_PAPER_OPEN",
        created_at__gte=start,
        payload__game_pk=game_pk,
    )
    return sum(int(x.payload.get("risk_cents") or 0) for x in events)


def _can_reenter(user, item, code):
    fingerprint = _fingerprint(item, code)
    start = _today_start()
    prior = EdgeAuditEvent.objects.filter(
        user=user,
        event_type="PORTFOLIO_PAPER_OPEN",
        created_at__gte=start,
        payload__fingerprint=fingerprint,
    ).exists()
    if prior:
        return False, "same_game_state_already_traded"

    ticker = item.get("ticker")
    open_trade = EdgePaperTrade.objects.filter(
        user=user,
        status="OPEN",
        signal__event_key__contains=f":{ticker}:",
        signal__event_key__startswith="PORTFOLIO:",
    ).exists()
    if open_trade:
        return False, "market_already_has_open_position"

    recent_exit = EdgeAuditEvent.objects.filter(
        user=user,
        event_type="PORTFOLIO_PAPER_EXIT",
        created_at__gte=timezone.now() - timedelta(minutes=REENTRY_COOLDOWN_MINUTES),
        payload__ticker=ticker,
    ).exists()
    if recent_exit:
        return False, "reentry_cooldown"
    return True, None


def _signal_for_item(user, item, code, fingerprint):
    event_key = f"PORTFOLIO:{code}:{item['ticker']}:{fingerprint}"
    return EdgeSignal.objects.create(
        user=user,
        sport="MLB",
        event_key=event_key,
        matchup=item["matchup"],
        game_state=item.get("game_state") or "",
        side=item["side"],
        market_price_cents=item["current_ask_cents"],
        model_probability_bps=int(round(item["model_probability_pct"] * 100)),
        edge_bps=int(round(item["model_edge_pct"] * 100)),
        opportunity_score=max(0, min(100, int(round(50 + item["model_edge_pct"] * 3)))),
        signal=f"STRATEGY_{code}",
    )


def _close_due_trades(user, boards):
    current = {}
    for code, board in boards.items():
        for item in board.get("signals", []):
            if item.get("ticker"):
                current[(code, item["ticker"])] = item

    closed = []
    open_trades = EdgePaperTrade.objects.filter(
        user=user,
        status="OPEN",
        signal__event_key__startswith="PORTFOLIO:",
    ).select_related("signal")
    now = timezone.now()
    for trade in open_trades:
        parts = trade.signal.event_key.split(":")
        if len(parts) < 4:
            continue
        code, ticker = parts[1], parts[2]
        hold_minutes = 20 if code == "A" else 30 if code == "B" else 20
        if trade.created_at > now - timedelta(minutes=hold_minutes):
            continue
        item = current.get((code, ticker))
        if not item or item.get("current_bid_cents") is None:
            continue
        exit_price = max(0, int(item["current_bid_cents"]))
        effective_exit = max(0.0, exit_price - 0.5)
        pnl = round(trade.risk_cents * (effective_exit / trade.entry_price_cents - 1))
        trade.exit_price_cents = exit_price
        trade.pnl_cents = pnl
        trade.status = "EXITED"
        trade.closed_at = now
        trade.save(update_fields=["exit_price_cents", "pnl_cents", "status", "closed_at"])
        EdgeAuditEvent.objects.create(
            user=user,
            event_type="PORTFOLIO_PAPER_EXIT",
            payload={
                "paper_trade_id": trade.id,
                "ticker": ticker,
                "strategy_code": code,
                "exit_reason": f"{hold_minutes}_MINUTE_TIME_EXIT",
                "pnl_cents": pnl,
            },
        )
        closed.append(_trade_payload(trade))
    return closed


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def portfolio_live(request):
    bankroll_cents = max(100, int(request.query_params.get("bankroll_cents") or 10000))
    boards = _strategy_boards()
    risk = _risk_snapshot(request.user, bankroll_cents)
    candidates = []
    for code, board in boards.items():
        for item in board.get("qualifying_signals", []):
            can_enter, blocked_reason = _can_reenter(request.user, item, code)
            game_limit = max(1, round(bankroll_cents * PER_GAME_RISK_PCT / 100))
            game_used = _game_risk_used(request.user, item.get("game_pk"))
            candidates.append({
                **item,
                "strategy_code": code,
                "can_enter": bool(can_enter and not risk["stop_new_entries"] and game_used < game_limit),
                "blocked_reason": blocked_reason if not can_enter else ("daily_risk_cap" if risk["stop_new_entries"] else ("game_risk_cap" if game_used >= game_limit else None)),
                "game_risk_used_cents": game_used,
                "game_risk_limit_cents": game_limit,
            })
    recent = EdgePaperTrade.objects.filter(user=request.user, signal__event_key__startswith="PORTFOLIO:").select_related("signal").order_by("-created_at")[:50]
    return Response({
        "mode": "paper_only",
        "live_money_enabled": False,
        "portfolio": risk,
        "rules": {
            "one_open_position_per_market": True,
            "averaging_down": False,
            "reentry_requires_new_game_state": True,
            "reentry_cooldown_minutes": REENTRY_COOLDOWN_MINUTES,
            "daily_risk_cap_pct": DAILY_RISK_PCT,
            "per_game_risk_cap_pct": PER_GAME_RISK_PCT,
            "default_per_entry_risk_pct": PER_ENTRY_RISK_PCT,
        },
        "candidates": candidates,
        "paper_trades": [_trade_payload(x) for x in recent],
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def portfolio_paper_tick(request):
    bankroll_cents = max(100, int(request.data.get("bankroll_cents") or 10000))
    boards = _strategy_boards()
    closed = _close_due_trades(request.user, boards)
    risk = _risk_snapshot(request.user, bankroll_cents)
    opened = []
    skipped = []

    if not risk["stop_new_entries"]:
        for code in ("A", "B"):
            board = boards[code]
            for item in board.get("qualifying_signals", []):
                risk = _risk_snapshot(request.user, bankroll_cents)
                if risk["stop_new_entries"]:
                    skipped.append({"ticker": item.get("ticker"), "strategy_code": code, "reason": "daily_risk_cap"})
                    continue
                can_enter, reason = _can_reenter(request.user, item, code)
                if not can_enter:
                    skipped.append({"ticker": item.get("ticker"), "strategy_code": code, "reason": reason})
                    continue

                daily_remaining = risk["daily_remaining_cents"]
                game_limit = max(1, round(bankroll_cents * PER_GAME_RISK_PCT / 100))
                game_used = _game_risk_used(request.user, item.get("game_pk"))
                game_remaining = max(0, game_limit - game_used)
                entry_target = max(1, round(bankroll_cents * PER_ENTRY_RISK_PCT / 100))
                risk_cents = min(entry_target, daily_remaining, game_remaining)
                if risk_cents <= 0:
                    skipped.append({"ticker": item.get("ticker"), "strategy_code": code, "reason": "risk_budget_exhausted"})
                    continue

                fingerprint = _fingerprint(item, code)
                signal = _signal_for_item(request.user, item, code, fingerprint)
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
                    event_type="PORTFOLIO_PAPER_OPEN",
                    payload={
                        "paper_trade_id": trade.id,
                        "ticker": item["ticker"],
                        "game_pk": item.get("game_pk"),
                        "strategy_code": code,
                        "fingerprint": fingerprint,
                        "risk_cents": risk_cents,
                        "bankroll_cents": bankroll_cents,
                    },
                )
                opened.append(_trade_payload(trade))

    final_risk = _risk_snapshot(request.user, bankroll_cents)
    recent = EdgePaperTrade.objects.filter(user=request.user, signal__event_key__startswith="PORTFOLIO:").select_related("signal").order_by("-created_at")[:50]
    return Response({
        "mode": "paper_only",
        "live_money_enabled": False,
        "opened": opened,
        "closed": closed,
        "skipped": skipped,
        "portfolio": final_risk,
        "paper_trades": [_trade_payload(x) for x in recent],
    })
