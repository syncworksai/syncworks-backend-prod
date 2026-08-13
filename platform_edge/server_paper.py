from __future__ import annotations

import math
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .live_data import get_live_mlb_board
from .models import EdgeAuditEvent, EdgePaperTrade, EdgeSignal, EdgeStrategy
from .portfolio_views import (
    PER_ENTRY_RISK_PCT,
    PER_GAME_RISK_PCT,
    _close_due_trades,
    _fingerprint,
    _signal_for_item,
    _strategy_boards,
)
from .strategy_e import FREEZE_VERSION, FROZEN_E_RULES, get_strategy_e_live_boards

BANKROLL_CENTS = 10000
DAILY_RISK_PCT_PER_STRATEGY = 1.0
LOCK_PAIR_MAX_CENTS = 99
NEAR_HEDGE_MAX_CENTS = 103
REENTRY_COOLDOWN_MINUTES = 5
AB_CODES = ("A", "B")
E_CODES = ("E1", "E2")


def _today_start():
    now = timezone.localtime()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _trade_code(trade: EdgePaperTrade) -> str | None:
    if not trade.signal:
        return None
    parts = str(trade.signal.event_key or "").split(":")
    return parts[1] if len(parts) >= 2 and parts[0] == "PORTFOLIO" else None


def _ticker_from_trade(trade: EdgePaperTrade) -> str | None:
    if not trade.signal:
        return None
    parts = str(trade.signal.event_key or "").split(":")
    return parts[2] if len(parts) >= 3 and parts[0] == "PORTFOLIO" else None


def _game_pk_from_trade(trade: EdgePaperTrade) -> int | None:
    if not trade.signal:
        return None
    parts = str(trade.signal.event_key or "").split(":")
    for part in reversed(parts):
        try:
            return int(part)
        except (TypeError, ValueError):
            continue
    return None


def _strategy_trades_today(user, code):
    return EdgePaperTrade.objects.filter(
        user=user,
        created_at__gte=_today_start(),
        signal__event_key__startswith=f"PORTFOLIO:{code}:",
    ).select_related("signal")


def _strategy_risk_snapshot(user, code, bankroll_cents=BANKROLL_CENTS):
    trades = _strategy_trades_today(user, code)
    daily_limit = max(1, round(bankroll_cents * DAILY_RISK_PCT_PER_STRATEGY / 100))
    used = trades.aggregate(total=Sum("risk_cents"))["total"] or 0
    open_risk = trades.filter(status="OPEN").aggregate(total=Sum("risk_cents"))["total"] or 0
    realized = trades.filter(status__in=("EXITED", "SETTLED")).aggregate(total=Sum("pnl_cents"))["total"] or 0
    return {
        "strategy_code": code,
        "bankroll_cents": bankroll_cents,
        "daily_limit_cents": daily_limit,
        "daily_used_cents": used,
        "daily_remaining_cents": max(0, daily_limit - used),
        "open_risk_cents": open_risk,
        "realized_pnl_cents": realized,
        "stop_new_entries": used >= daily_limit,
    }


def _strategy_game_used(user, code, game_pk):
    events = EdgeAuditEvent.objects.filter(
        user=user,
        event_type="PORTFOLIO_PAPER_OPEN",
        created_at__gte=_today_start(),
        payload__strategy_code=code,
        payload__game_pk=game_pk,
    )
    return sum(int(event.payload.get("risk_cents") or 0) for event in events)


def _can_reenter_shadow(user, item, code):
    fingerprint = _fingerprint(item, code)
    if EdgeAuditEvent.objects.filter(
        user=user,
        event_type="PORTFOLIO_PAPER_OPEN",
        created_at__gte=_today_start(),
        payload__strategy_code=code,
        payload__fingerprint=fingerprint,
    ).exists():
        return False, "same_game_state_already_traded"

    ticker = item.get("ticker")
    if EdgePaperTrade.objects.filter(
        user=user,
        status="OPEN",
        signal__event_key__startswith=f"PORTFOLIO:{code}:{ticker}:",
    ).exists():
        return False, "strategy_market_already_open"

    if EdgeAuditEvent.objects.filter(
        user=user,
        event_type="PORTFOLIO_PAPER_EXIT",
        created_at__gte=timezone.now() - timedelta(minutes=REENTRY_COOLDOWN_MINUTES),
        payload__strategy_code=code,
        payload__ticker=ticker,
    ).exists():
        return False, "reentry_cooldown"
    return True, None


def _live_pair_index(board=None):
    board = board or get_live_mlb_board()
    index = {}
    for game in board.get("games", []):
        away_market = game.get("away_market") or {}
        home_market = game.get("home_market") or {}
        away_ticker = away_market.get("ticker")
        home_ticker = home_market.get("ticker")
        matchup = f"{game.get('away', {}).get('code')} @ {game.get('home', {}).get('code')}"
        common = {
            "game_pk": game.get("game_pk"),
            "matchup": matchup,
            "game_state": game.get("game_state"),
            "inning": int(game.get("inning") or 0),
            "status": game.get("status"),
            "is_live": bool(game.get("is_live")),
            "away_code": game.get("away", {}).get("code"),
            "home_code": game.get("home", {}).get("code"),
            "away_score": int(game.get("away", {}).get("score") or 0),
            "home_score": int(game.get("home", {}).get("score") or 0),
        }
        if away_ticker and home_ticker:
            index[away_ticker] = {
                **common,
                "current_ask_cents": away_market.get("yes_ask_cents"),
                "current_bid_cents": away_market.get("yes_bid_cents"),
                "opposite_ticker": home_ticker,
                "opposite_side": f"{game.get('home', {}).get('code')} YES",
                "opposite_ask_cents": home_market.get("yes_ask_cents"),
                "opposite_bid_cents": home_market.get("yes_bid_cents"),
            }
            index[home_ticker] = {
                **common,
                "current_ask_cents": home_market.get("yes_ask_cents"),
                "current_bid_cents": home_market.get("yes_bid_cents"),
                "opposite_ticker": away_ticker,
                "opposite_side": f"{game.get('away', {}).get('code')} YES",
                "opposite_ask_cents": away_market.get("yes_ask_cents"),
                "opposite_bid_cents": away_market.get("yes_bid_cents"),
            }
    return index


def _hedge_math(trade: EdgePaperTrade, pair: dict):
    ask = pair.get("opposite_ask_cents")
    if ask is None or not trade.entry_price_cents:
        return None
    opposite_entry = min(99, int(ask) + 1)
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
        "strategy_code": _trade_code(trade),
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
        math_row = _hedge_math(trade, pair)
        if not math_row or math_row["state"] == "NO_HEDGE":
            continue
        opportunities.append(math_row)
        if math_row["state"] == "LOCK_PROFIT":
            exists = EdgeAuditEvent.objects.filter(
                user=user,
                event_type="PORTFOLIO_HEDGE_LOCK_FOUND",
                payload__primary_trade_id=trade.id,
            ).exists()
            if not exists:
                EdgeAuditEvent.objects.create(user=user, event_type="PORTFOLIO_HEDGE_LOCK_FOUND", payload=math_row)
    opportunities.sort(key=lambda x: (x["state"] == "LOCK_PROFIT", x["locked_roi_pct"]), reverse=True)
    return opportunities


def _open_ab_shadow_trades(user, boards, bankroll_cents):
    opened, skipped = [], []
    for code in AB_CODES:
        risk = _strategy_risk_snapshot(user, code, bankroll_cents)
        for item in boards[code].get("qualifying_signals", []):
            risk = _strategy_risk_snapshot(user, code, bankroll_cents)
            if risk["stop_new_entries"]:
                skipped.append({"ticker": item.get("ticker"), "strategy_code": code, "reason": "strategy_daily_risk_cap"})
                continue
            can_enter, reason = _can_reenter_shadow(user, item, code)
            if not can_enter:
                skipped.append({"ticker": item.get("ticker"), "strategy_code": code, "reason": reason})
                continue
            game_limit = max(1, round(bankroll_cents * PER_GAME_RISK_PCT / 100))
            game_used = _strategy_game_used(user, code, item.get("game_pk"))
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
                    "runner": "server_shadow",
                    "rules_frozen": True,
                },
            )
            opened.append(trade.id)
    return opened, skipped


def _round_risk(value):
    return max(1, int(math.floor(float(value) + 0.5)))


def _e_projected_risk_cents(rule, bankroll_cents):
    base = _round_risk(bankroll_cents * float(rule["base_risk_pct"]) / 100.0)
    hedge = _round_risk(base * float(rule["hedge_multiple"]))
    return base, hedge, base + hedge


def _e_reserved_today(user, code):
    events = EdgeAuditEvent.objects.filter(
        user=user,
        event_type="PORTFOLIO_E_BASE_OPEN",
        created_at__gte=_today_start(),
        payload__strategy_code=code,
    )
    return sum(int(event.payload.get("projected_total_risk_cents") or 0) for event in events)


def _open_e_bases(user, eboards, bankroll_cents):
    opened, skipped = [], []
    daily_limit = max(1, round(bankroll_cents * DAILY_RISK_PCT_PER_STRATEGY / 100))
    for code in E_CODES:
        rule = FROZEN_E_RULES[code]
        base_risk, hedge_risk, projected = _e_projected_risk_cents(rule, bankroll_cents)
        for item in eboards[code].get("qualifying_signals", []):
            game_pk = item.get("game_pk")
            existing = EdgePaperTrade.objects.filter(
                user=user,
                signal__event_key=f"PORTFOLIO:{code}:{item['favorite_ticker']}:BASE:{game_pk}",
            ).exclude(status="SKIPPED").exists()
            if existing:
                continue
            reserved = _e_reserved_today(user, code)
            if reserved + projected > daily_limit:
                skipped.append({"strategy_code": code, "game_pk": game_pk, "reason": "strategy_daily_projected_risk_cap"})
                continue
            entry_price = min(99, int(item["favorite_ask_cents"]) + 1)
            signal = EdgeSignal.objects.create(
                user=user,
                sport="MLB",
                event_key=f"PORTFOLIO:{code}:{item['favorite_ticker']}:BASE:{game_pk}",
                matchup=item["matchup"],
                game_state=item.get("game_state") or "",
                side=f"{item['favorite_code']} YES",
                market_price_cents=int(item["favorite_ask_cents"]),
                model_probability_bps=int(round(float(item["pregame_favorite_probability_pct"]) * 100)),
                edge_bps=0,
                opportunity_score=50,
                signal=f"STRATEGY_{code}",
            )
            trade = EdgePaperTrade.objects.create(
                user=user,
                signal=signal,
                side=f"{item['favorite_code']} YES",
                risk_cents=base_risk,
                entry_price_cents=entry_price,
                status="OPEN",
            )
            payload = {
                "paper_trade_id": trade.id,
                "ticker": item["favorite_ticker"],
                "game_pk": game_pk,
                "strategy_code": code,
                "leg": "BASE_FAVORITE",
                "risk_cents": base_risk,
                "planned_hedge_risk_cents": hedge_risk,
                "projected_total_risk_cents": projected,
                "pregame_favorite_probability_pct": item["pregame_favorite_probability_pct"],
                "freeze_version": FREEZE_VERSION,
                "runner": "server_shadow",
                "rules_frozen": True,
            }
            EdgeAuditEvent.objects.create(user=user, event_type="PORTFOLIO_E_BASE_OPEN", payload=payload)
            EdgeAuditEvent.objects.create(user=user, event_type="PORTFOLIO_PAPER_OPEN", payload=payload)
            opened.append(trade.id)
    return opened, skipped


def _manage_e_hedges(user, eboards, bankroll_cents):
    opened, closed = [], []
    by_game = {
        (code, item["game_pk"]): item
        for code in E_CODES
        for item in eboards[code].get("signals", [])
    }

    bases = EdgePaperTrade.objects.filter(
        user=user,
        status="OPEN",
        signal__event_key__regex=r"^PORTFOLIO:E[12]:.*:BASE:",
    ).select_related("signal")
    for base in bases:
        code = _trade_code(base)
        game_pk = _game_pk_from_trade(base)
        item = by_game.get((code, game_pk))
        if not item or not item.get("hedge_triggered_now"):
            continue
        hedge_key = f"PORTFOLIO:{code}:{item['dog_ticker']}:HEDGE:{game_pk}"
        if EdgePaperTrade.objects.filter(user=user, signal__event_key=hedge_key).exclude(status="SKIPPED").exists():
            continue
        rule = FROZEN_E_RULES[code]
        _, hedge_risk, _ = _e_projected_risk_cents(rule, bankroll_cents)
        entry_price = min(99, int(item["dog_ask_cents"]) + 1)
        signal = EdgeSignal.objects.create(
            user=user,
            sport="MLB",
            event_key=hedge_key,
            matchup=item["matchup"],
            game_state=item.get("game_state") or "",
            side=f"{item['dog_code']} YES",
            market_price_cents=int(item["dog_ask_cents"]),
            model_probability_bps=max(0, 10000 - int(round(float(item["pregame_favorite_probability_pct"]) * 100))),
            edge_bps=0,
            opportunity_score=50,
            signal=f"STRATEGY_{code}",
        )
        hedge = EdgePaperTrade.objects.create(
            user=user,
            signal=signal,
            side=f"{item['dog_code']} YES",
            risk_cents=hedge_risk,
            entry_price_cents=entry_price,
            status="OPEN",
        )
        payload = {
            "paper_trade_id": hedge.id,
            "base_trade_id": base.id,
            "ticker": item["dog_ticker"],
            "game_pk": game_pk,
            "strategy_code": code,
            "leg": "DYNAMIC_HEDGE",
            "risk_cents": hedge_risk,
            "favorite_trigger_cents": item["favorite_ask_cents"],
            "hedge_entry_cents": entry_price,
            "hedge_target_cents": entry_price + int(rule["hedge_rebound_target_cents"]),
            "freeze_version": FREEZE_VERSION,
            "runner": "server_shadow",
            "rules_frozen": True,
        }
        EdgeAuditEvent.objects.create(user=user, event_type="PORTFOLIO_E_HEDGE_OPEN", payload=payload)
        EdgeAuditEvent.objects.create(user=user, event_type="PORTFOLIO_PAPER_OPEN", payload=payload)
        opened.append(hedge.id)

    hedges = EdgePaperTrade.objects.filter(
        user=user,
        status="OPEN",
        signal__event_key__regex=r"^PORTFOLIO:E[12]:.*:HEDGE:",
    ).select_related("signal")
    for hedge in hedges:
        code = _trade_code(hedge)
        game_pk = _game_pk_from_trade(hedge)
        item = by_game.get((code, game_pk))
        if not item or item.get("dog_bid_cents") is None:
            continue
        effective_bid = max(0.0, float(item["dog_bid_cents"]) - 0.5)
        target = float(hedge.entry_price_cents) + float(FROZEN_E_RULES[code]["hedge_rebound_target_cents"])
        if effective_bid < target:
            continue
        exit_price = int(item["dog_bid_cents"])
        pnl = round(hedge.risk_cents * (effective_bid / hedge.entry_price_cents - 1))
        hedge.exit_price_cents = exit_price
        hedge.pnl_cents = pnl
        hedge.status = "EXITED"
        hedge.closed_at = timezone.now()
        hedge.save(update_fields=["exit_price_cents", "pnl_cents", "status", "closed_at"])
        EdgeAuditEvent.objects.create(user=user, event_type="PORTFOLIO_PAPER_EXIT", payload={
            "paper_trade_id": hedge.id,
            "ticker": _ticker_from_trade(hedge),
            "game_pk": game_pk,
            "strategy_code": code,
            "leg": "DYNAMIC_HEDGE",
            "exit_reason": "FROZEN_5C_REBOUND_TARGET",
            "pnl_cents": pnl,
            "freeze_version": FREEZE_VERSION,
        })
        closed.append(hedge.id)
    return opened, closed


def _settle_e_finals(user, board):
    games = {int(game["game_pk"]): game for game in board.get("games", []) if game.get("game_pk") is not None}
    settled = []
    trades = EdgePaperTrade.objects.filter(
        user=user,
        status="OPEN",
        signal__event_key__regex=r"^PORTFOLIO:E[12]:",
    ).select_related("signal")
    for trade in trades:
        game_pk = _game_pk_from_trade(trade)
        game = games.get(game_pk)
        if not game or game.get("is_live"):
            continue
        status_text = str(game.get("status") or "").lower()
        if not any(word in status_text for word in ("final", "completed", "game over")):
            continue
        away_score = int(game.get("away", {}).get("score") or 0)
        home_score = int(game.get("home", {}).get("score") or 0)
        if away_score == home_score:
            continue
        winner = game.get("away", {}).get("code") if away_score > home_score else game.get("home", {}).get("code")
        side_code = str(trade.side or "").split(" ", 1)[0]
        won = side_code == winner
        exit_price = 100 if won else 0
        pnl = round(trade.risk_cents * (100.0 / trade.entry_price_cents - 1)) if won else -int(trade.risk_cents)
        trade.exit_price_cents = exit_price
        trade.pnl_cents = pnl
        trade.status = "SETTLED"
        trade.closed_at = timezone.now()
        trade.save(update_fields=["exit_price_cents", "pnl_cents", "status", "closed_at"])
        EdgeAuditEvent.objects.create(user=user, event_type="PORTFOLIO_PAPER_EXIT", payload={
            "paper_trade_id": trade.id,
            "ticker": _ticker_from_trade(trade),
            "game_pk": game_pk,
            "strategy_code": _trade_code(trade),
            "exit_reason": "MLB_FINAL_SETTLEMENT",
            "winner": winner,
            "pnl_cents": pnl,
            "freeze_version": FREEZE_VERSION,
        })
        settled.append(trade.id)
    return settled


def run_for_user(user, bankroll_cents=BANKROLL_CENTS, board=None):
    board = board or get_live_mlb_board()
    pair_index = _live_pair_index(board)
    ab_boards = _strategy_boards()
    e_boards = get_strategy_e_live_boards(board)

    closed_ab = _close_due_trades(user, ab_boards)
    settled_e = _settle_e_finals(user, board)
    opened_ab, skipped_ab = _open_ab_shadow_trades(user, ab_boards, bankroll_cents)
    opened_e, skipped_e = _open_e_bases(user, e_boards, bankroll_cents)
    opened_hedges, closed_hedges = _manage_e_hedges(user, e_boards, bankroll_cents)
    hedge_opportunities = _discover_hedges(user, pair_index=pair_index)

    strategy_snapshots = {code: _strategy_risk_snapshot(user, code, bankroll_cents) for code in (*AB_CODES, *E_CODES)}
    EdgeAuditEvent.objects.create(
        user=user,
        event_type="PORTFOLIO_SERVER_TICK",
        payload={
            "bankroll_cents_per_strategy": bankroll_cents,
            "rules_frozen": True,
            "freeze_version": FREEZE_VERSION,
            "opened_count": len(opened_ab) + len(opened_e) + len(opened_hedges),
            "closed_count": len(closed_ab) + len(settled_e) + len(closed_hedges),
            "skipped_count": len(skipped_ab) + len(skipped_e),
            "hedge_lock_count": sum(x["state"] == "LOCK_PROFIT" for x in hedge_opportunities),
            "strategy_snapshots": strategy_snapshots,
        },
    )
    return {
        "opened_count": len(opened_ab) + len(opened_e) + len(opened_hedges),
        "closed_count": len(closed_ab) + len(settled_e) + len(closed_hedges),
        "skipped_count": len(skipped_ab) + len(skipped_e),
        "hedge_lock_count": sum(x["state"] == "LOCK_PROFIT" for x in hedge_opportunities),
        "strategy_snapshots": strategy_snapshots,
    }


def _eligible_users():
    ids = EdgeStrategy.objects.values_list("user_id", flat=True).distinct()
    return get_user_model().objects.filter(id__in=ids, is_active=True)


@api_view(["POST"])
@permission_classes([AllowAny])
def system_paper_tick(request):
    # Paper-only scheduler endpoint. It has no exchange-order path.
    board = get_live_mlb_board()
    results = []
    for user in _eligible_users():
        try:
            results.append(run_for_user(user, BANKROLL_CENTS, board=board))
        except Exception as exc:
            results.append({"error": True, "detail": str(exc)[:160]})
    return Response({
        "mode": "paper_only",
        "live_money_enabled": False,
        "rules_frozen": True,
        "freeze_version": FREEZE_VERSION,
        "ran_at": timezone.now(),
        "users_processed": len(results),
        "opened_count": sum(x.get("opened_count", 0) for x in results),
        "closed_count": sum(x.get("closed_count", 0) for x in results),
        "hedge_lock_count": sum(x.get("hedge_lock_count", 0) for x in results),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def server_paper_status(request):
    board = get_live_mlb_board()
    pair_index = _live_pair_index(board)
    current = _discover_hedges(request.user, pair_index=pair_index)
    latest_tick = EdgeAuditEvent.objects.filter(user=request.user, event_type="PORTFOLIO_SERVER_TICK").first()
    history = EdgeAuditEvent.objects.filter(user=request.user, event_type="PORTFOLIO_HEDGE_LOCK_FOUND")[:25]
    return Response({
        "mode": "paper_only",
        "background_runner": True,
        "rules_frozen": True,
        "freeze_version": FREEZE_VERSION,
        "scheduler_target_seconds": 300,
        "last_server_tick_at": latest_tick.created_at if latest_tick else None,
        "last_server_tick": latest_tick.payload if latest_tick else None,
        "strategy_risk": {code: _strategy_risk_snapshot(request.user, code, BANKROLL_CENTS) for code in (*AB_CODES, *E_CODES)},
        "current_hedges": current,
        "hedge_history": [{"id": x.id, "found_at": x.created_at, **x.payload} for x in history],
        "frozen_e_rules": FROZEN_E_RULES,
        "hedge_rule": {
            "method": "matched_contracts",
            "lock_profit_when_pair_cost_cents_at_or_below": LOCK_PAIR_MAX_CENTS,
            "near_hedge_at_or_below": NEAR_HEDGE_MAX_CENTS,
            "note": "Hedge Lab is observational and separate from frozen E1/E2 dynamic-hedge execution.",
        },
    })
