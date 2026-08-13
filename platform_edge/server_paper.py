from __future__ import annotations

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .live_data import get_live_mlb_board
from .models import EdgeAuditEvent, EdgePaperTrade, EdgeStrategy
from .portfolio_views import (
    PER_ENTRY_RISK_PCT,
    PER_GAME_RISK_PCT,
    _can_reenter,
    _close_due_trades,
    _fingerprint,
    _game_risk_used,
    _risk_snapshot,
    _signal_for_item,
    _strategy_boards,
)

BANKROLL_CENTS = 10000
LOCK_PAIR_MAX_CENTS = 99
NEAR_HEDGE_MAX_CENTS = 103


def _ticker_from_trade(trade: EdgePaperTrade) -> str | None:
    if not trade.signal:
        return None
    parts = str(trade.signal.event_key or "").split(":")
    return parts[2] if len(parts) >= 4 and parts[0] == "PORTFOLIO" else None


def _live_pair_index():
    board = get_live_mlb_board()
    index = {}
    for game in board.get("games", []):
        away_market = game.get("away_market") or {}
        home_market = game.get("home_market") or {}
        away_ticker = away_market.get("ticker")
        home_ticker = home_market.get("ticker")
        matchup = f"{game.get('away', {}).get('code')} @ {game.get('home', {}).get('code')}"
        if away_ticker and home_ticker:
            index[away_ticker] = {
                "game_pk": game.get("game_pk"),
                "matchup": matchup,
                "opposite_ticker": home_ticker,
                "opposite_side": f"{game.get('home', {}).get('code')} YES",
                "opposite_ask_cents": home_market.get("yes_ask_cents"),
                "game_state": game.get("game_state"),
            }
            index[home_ticker] = {
                "game_pk": game.get("game_pk"),
                "matchup": matchup,
                "opposite_ticker": away_ticker,
                "opposite_side": f"{game.get('away', {}).get('code')} YES",
                "opposite_ask_cents": away_market.get("yes_ask_cents"),
                "game_state": game.get("game_state"),
            }
    return index


def _hedge_math(trade: EdgePaperTrade, pair: dict):
    ask = pair.get("opposite_ask_cents")
    if ask is None or not trade.entry_price_cents:
        return None
    opposite_entry = min(99, int(ask) + 1)  # same 1c simulated entry friction as primary paper entries
    primary_entry = int(trade.entry_price_cents)
    pair_cost = primary_entry + opposite_entry
    contracts = float(trade.risk_cents) / float(primary_entry)
    hedge_cost = contracts * opposite_entry
    guaranteed_payout = contracts * 100.0
    locked_profit = guaranteed_payout - float(trade.risk_cents) - hedge_cost
    combined_cost = float(trade.risk_cents) + hedge_cost
    locked_roi = (locked_profit / combined_cost * 100.0) if combined_cost > 0 else 0.0
    state = "LOCK_PROFIT" if pair_cost <= LOCK_PAIR_MAX_CENTS else "NEAR_HEDGE" if pair_cost <= NEAR_HEDGE_MAX_CENTS else "NO_HEDGE"
    return {
        "state": state,
        "primary_trade_id": trade.id,
        "primary_side": trade.side,
        "primary_entry_cents": primary_entry,
        "primary_risk_cents": trade.risk_cents,
        "opposite_ticker": pair.get("opposite_ticker"),
        "opposite_side": pair.get("opposite_side"),
        "opposite_entry_cents": opposite_entry,
        "pair_cost_cents_per_contract": pair_cost,
        "contracts": round(contracts, 4),
        "hedge_cost_cents": round(hedge_cost, 2),
        "guaranteed_payout_cents": round(guaranteed_payout, 2),
        "locked_profit_cents": round(locked_profit, 2),
        "locked_roi_pct": round(locked_roi, 2),
        "matchup": pair.get("matchup"),
        "game_pk": pair.get("game_pk"),
        "game_state": pair.get("game_state"),
        "why": (
            f"Matched-contract hedge costs {pair_cost}c total per $1 payout, leaving {100 - pair_cost}c gross locked value per contract."
            if state == "LOCK_PROFIT"
            else f"Opposite side is close, but the two entry prices total {pair_cost}c after simulated friction."
        ),
    }


def _discover_hedges(user, pair_index=None):
    pair_index = pair_index if pair_index is not None else _live_pair_index()
    opportunities = []
    open_trades = EdgePaperTrade.objects.filter(
        user=user,
        status="OPEN",
        signal__event_key__startswith="PORTFOLIO:",
    ).select_related("signal")
    for trade in open_trades:
        ticker = _ticker_from_trade(trade)
        pair = pair_index.get(ticker) if ticker else None
        if not pair:
            continue
        math = _hedge_math(trade, pair)
        if not math or math["state"] == "NO_HEDGE":
            continue
        opportunities.append(math)
        if math["state"] == "LOCK_PROFIT":
            exists = EdgeAuditEvent.objects.filter(
                user=user,
                event_type="PORTFOLIO_HEDGE_LOCK_FOUND",
                payload__primary_trade_id=trade.id,
            ).exists()
            if not exists:
                EdgeAuditEvent.objects.create(user=user, event_type="PORTFOLIO_HEDGE_LOCK_FOUND", payload=math)
    opportunities.sort(key=lambda x: (x["state"] == "LOCK_PROFIT", x["locked_roi_pct"]), reverse=True)
    return opportunities


def run_for_user(user, bankroll_cents=BANKROLL_CENTS, pair_index=None):
    boards = _strategy_boards()
    closed = _close_due_trades(user, boards)
    risk = _risk_snapshot(user, bankroll_cents)
    opened, skipped = [], []

    if not risk["stop_new_entries"]:
        for code in ("A", "B"):
            for item in boards[code].get("qualifying_signals", []):
                risk = _risk_snapshot(user, bankroll_cents)
                if risk["stop_new_entries"]:
                    skipped.append({"ticker": item.get("ticker"), "strategy_code": code, "reason": "daily_risk_cap"})
                    continue
                can_enter, reason = _can_reenter(user, item, code)
                if not can_enter:
                    skipped.append({"ticker": item.get("ticker"), "strategy_code": code, "reason": reason})
                    continue
                game_limit = max(1, round(bankroll_cents * PER_GAME_RISK_PCT / 100))
                game_used = _game_risk_used(user, item.get("game_pk"))
                entry_target = max(1, round(bankroll_cents * PER_ENTRY_RISK_PCT / 100))
                risk_cents = min(entry_target, risk["daily_remaining_cents"], max(0, game_limit - game_used))
                if risk_cents <= 0:
                    skipped.append({"ticker": item.get("ticker"), "strategy_code": code, "reason": "risk_budget_exhausted"})
                    continue
                fingerprint = _fingerprint(item, code)
                signal = _signal_for_item(user, item, code, fingerprint)
                entry_price = min(99, int(item["current_ask_cents"]) + 1)
                trade = EdgePaperTrade.objects.create(
                    user=user,
                    signal=signal,
                    side=item["side"],
                    risk_cents=risk_cents,
                    entry_price_cents=entry_price,
                    status="OPEN",
                )
                EdgeAuditEvent.objects.create(
                    user=user,
                    event_type="PORTFOLIO_PAPER_OPEN",
                    payload={
                        "paper_trade_id": trade.id,
                        "ticker": item["ticker"],
                        "game_pk": item.get("game_pk"),
                        "strategy_code": code,
                        "fingerprint": fingerprint,
                        "risk_cents": risk_cents,
                        "bankroll_cents": bankroll_cents,
                        "runner": "server",
                    },
                )
                opened.append(trade.id)

    hedge_opportunities = _discover_hedges(user, pair_index=pair_index)
    final_risk = _risk_snapshot(user, bankroll_cents)
    EdgeAuditEvent.objects.create(
        user=user,
        event_type="PORTFOLIO_SERVER_TICK",
        payload={
            "bankroll_cents": bankroll_cents,
            "opened_count": len(opened),
            "closed_count": len(closed),
            "skipped_count": len(skipped),
            "hedge_lock_count": sum(x["state"] == "LOCK_PROFIT" for x in hedge_opportunities),
            "open_risk_cents": final_risk.get("open_risk_cents", 0),
            "realized_pnl_cents": final_risk.get("realized_pnl_cents", 0),
        },
    )
    return {
        "opened_count": len(opened),
        "closed_count": len(closed),
        "skipped_count": len(skipped),
        "hedge_lock_count": sum(x["state"] == "LOCK_PROFIT" for x in hedge_opportunities),
    }


def _eligible_users():
    ids = EdgeStrategy.objects.values_list("user_id", flat=True).distinct()
    return get_user_model().objects.filter(id__in=ids, is_active=True)


@api_view(["POST"])
@permission_classes([AllowAny])
def system_paper_tick(request):
    # Safe scheduler endpoint: paper-only, no exchange orders, idempotency remains enforced by portfolio rules.
    pair_index = _live_pair_index()
    results = []
    for user in _eligible_users():
        try:
            results.append(run_for_user(user, BANKROLL_CENTS, pair_index=pair_index))
        except Exception:
            results.append({"error": True})
    return Response({
        "mode": "paper_only",
        "live_money_enabled": False,
        "ran_at": timezone.now(),
        "users_processed": len(results),
        "opened_count": sum(x.get("opened_count", 0) for x in results),
        "closed_count": sum(x.get("closed_count", 0) for x in results),
        "hedge_lock_count": sum(x.get("hedge_lock_count", 0) for x in results),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def server_paper_status(request):
    pair_index = _live_pair_index()
    current = _discover_hedges(request.user, pair_index=pair_index)
    latest_tick = EdgeAuditEvent.objects.filter(user=request.user, event_type="PORTFOLIO_SERVER_TICK").first()
    history = EdgeAuditEvent.objects.filter(user=request.user, event_type="PORTFOLIO_HEDGE_LOCK_FOUND")[:25]
    return Response({
        "mode": "paper_only",
        "background_runner": True,
        "scheduler_target_seconds": 300,
        "last_server_tick_at": latest_tick.created_at if latest_tick else None,
        "last_server_tick": latest_tick.payload if latest_tick else None,
        "current_hedges": current,
        "hedge_history": [{"id": x.id, "found_at": x.created_at, **x.payload} for x in history],
        "hedge_rule": {
            "method": "matched_contracts",
            "lock_profit_when_pair_cost_cents_at_or_below": LOCK_PAIR_MAX_CENTS,
            "near_hedge_at_or_below": NEAR_HEDGE_MAX_CENTS,
            "note": "A $1 stake on each side is not automatically a lock. EDGE sizes the opposite side to match the number of contracts held on the first side.",
        },
    })
