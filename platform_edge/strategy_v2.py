from __future__ import annotations

import math
from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .live_data import get_live_mlb_board
from .models import EdgeAuditEvent, EdgePaperTrade, EdgeSignal
from .portfolio_views import _strategy_boards

V2_VERSION = "2026-08-24-v2.0"
BANKROLL_CENTS = 5000
UNIT_RISK_CENTS = 100
DAILY_MAX_RISK_CENTS = 500
PER_GAME_MAX_RISK_CENTS = 300
REENTRY_COOLDOWN_MINUTES = 5
MAX_REENTRIES_PER_GAME = 3

STRATEGIES = {
    "HOLD": {
        "name": "Hold",
        "short": "Hold to settlement",
        "exit_plan": "Hold the PRIME entry to final settlement.",
        "reentry": False,
    },
    "R50": {
        "name": "Reprice +50%",
        "short": "Full exit at 1.50×",
        "exit_plan": "Sell the full paper position when the executable bid reaches 1.50× entry.",
        "reentry": False,
    },
    "X2": {
        "name": "2× Full Exit",
        "short": "Full exit at 2.00×",
        "exit_plan": "Sell the full paper position when the executable bid reaches 2.00× entry.",
        "reentry": False,
    },
    "X2R": {
        "name": "2× Recover",
        "short": "Recover principal at 2×",
        "exit_plan": "At 2.00×, sell half the contracts to recover approximately the original $1; hold the remaining half to settlement.",
        "reentry": False,
    },
    "DYN": {
        "name": "Dynamic",
        "short": "Target + invalidation exit",
        "exit_plan": "Exit at 2.00×, when model edge falls to 0% or worse, or after 30 minutes; otherwise settle at final.",
        "reentry": False,
    },
    "DYNRE": {
        "name": "Dynamic + Re-entry",
        "short": "Dynamic exit + fresh PRIME re-entry",
        "exit_plan": "Use Dynamic exits, then allow a fresh qualifying game-state re-entry after a 5-minute cooldown, up to 3 entries per game.",
        "reentry": True,
    },
}


def _today_start():
    now = timezone.localtime()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _event_parts(trade):
    if not trade.signal:
        return []
    return str(trade.signal.event_key or "").split(":")


def _code(trade):
    parts = _event_parts(trade)
    return parts[1] if len(parts) >= 2 and parts[0] == "V2" else None


def _ticker(trade):
    parts = _event_parts(trade)
    return parts[2] if len(parts) >= 3 and parts[0] == "V2" else None


def _game_pk(trade):
    parts = _event_parts(trade)
    try:
        return int(parts[3]) if len(parts) >= 4 and parts[0] == "V2" else None
    except (TypeError, ValueError):
        return None


def _market_index(board):
    out = {}
    games = {}
    for game in board.get("games", []):
        game_pk = game.get("game_pk")
        if game_pk is not None:
            games[int(game_pk)] = game
        for side_key in ("away", "home"):
            market = game.get(f"{side_key}_market") or {}
            ticker = market.get("ticker")
            team = (game.get(side_key) or {}).get("code")
            if not ticker:
                continue
            out[ticker] = {
                "ticker": ticker,
                "team": team,
                "game_pk": game_pk,
                "matchup": f"{(game.get('away') or {}).get('code')} @ {(game.get('home') or {}).get('code')}",
                "game_state": game.get("game_state"),
                "bid_cents": market.get("yes_bid_cents"),
                "ask_cents": market.get("yes_ask_cents"),
                "is_live": bool(game.get("is_live")),
                "status": game.get("status"),
            }
    return out, games


def _signal_index():
    boards = _strategy_boards()
    all_rows = {}
    qualifying = {}
    for source_code, board in boards.items():
        for row in board.get("signals", []):
            ticker = row.get("ticker")
            if not ticker:
                continue
            current = all_rows.get(ticker)
            if current is None or float(row.get("model_edge_pct") or -999) > float(current.get("model_edge_pct") or -999):
                all_rows[ticker] = {**row, "source_strategy": source_code}
        for row in board.get("qualifying_signals", []):
            ticker = row.get("ticker")
            if not ticker:
                continue
            current = qualifying.get(ticker)
            if current is None or float(row.get("model_edge_pct") or -999) > float(current.get("model_edge_pct") or -999):
                qualifying[ticker] = {**row, "source_strategy": source_code}
    ranked = sorted(qualifying.values(), key=lambda row: float(row.get("model_edge_pct") or 0), reverse=True)
    return all_rows, ranked


def _strategy_trades(user, code):
    return EdgePaperTrade.objects.filter(user=user, signal__event_key__startswith=f"V2:{code}:").select_related("signal")


def _risk_today(user, code):
    rows = _strategy_trades(user, code).filter(created_at__gte=_today_start())
    return rows.aggregate(total=Sum("risk_cents"))["total"] or 0


def _game_entries(user, code, game_pk):
    return EdgeAuditEvent.objects.filter(
        user=user,
        event_type="EDGE_V2_OPEN",
        payload__strategy_code=code,
        payload__game_pk=game_pk,
    ).count()


def _game_risk_today(user, code, game_pk):
    events = EdgeAuditEvent.objects.filter(
        user=user,
        event_type="EDGE_V2_OPEN",
        created_at__gte=_today_start(),
        payload__strategy_code=code,
        payload__game_pk=game_pk,
    )
    return sum(int(event.payload.get("risk_cents") or 0) for event in events)


def _fingerprint(row):
    return "|".join([
        str(row.get("source_strategy") or ""),
        str(row.get("ticker") or ""),
        str(row.get("game_pk") or ""),
        str(row.get("inning") or ""),
        str(row.get("game_state") or ""),
        str(row.get("deficit") or ""),
    ])


def _can_open(user, code, row):
    game_pk = row.get("game_pk")
    ticker = row.get("ticker")
    if _risk_today(user, code) + UNIT_RISK_CENTS > DAILY_MAX_RISK_CENTS:
        return False, "daily_strategy_risk_cap"
    if _game_risk_today(user, code, game_pk) + UNIT_RISK_CENTS > PER_GAME_MAX_RISK_CENTS:
        return False, "game_risk_cap"
    if _strategy_trades(user, code).filter(status="OPEN", signal__event_key__startswith=f"V2:{code}:{ticker}:").exists():
        return False, "market_already_open"

    fingerprint = _fingerprint(row)
    if EdgeAuditEvent.objects.filter(user=user, event_type="EDGE_V2_OPEN", payload__strategy_code=code, payload__fingerprint=fingerprint).exists():
        return False, "same_state_already_traded"

    if not STRATEGIES[code]["reentry"]:
        if EdgeAuditEvent.objects.filter(user=user, event_type="EDGE_V2_OPEN", payload__strategy_code=code, payload__game_pk=game_pk).exists():
            return False, "one_entry_per_game"
    else:
        if _game_entries(user, code, game_pk) >= MAX_REENTRIES_PER_GAME:
            return False, "game_reentry_cap"
        recent = EdgeAuditEvent.objects.filter(
            user=user,
            event_type="EDGE_V2_EXIT",
            payload__strategy_code=code,
            payload__game_pk=game_pk,
            created_at__gte=timezone.now() - timedelta(minutes=REENTRY_COOLDOWN_MINUTES),
        ).exists()
        if recent:
            return False, "reentry_cooldown"
    return True, None


def _open_trade(user, code, row):
    game_pk = int(row.get("game_pk"))
    ticker = row["ticker"]
    entry = min(99, int(row["current_ask_cents"]) + 1)
    now_stamp = int(timezone.now().timestamp())
    signal = EdgeSignal.objects.create(
        user=user,
        sport="MLB",
        event_key=f"V2:{code}:{ticker}:{game_pk}:{now_stamp}",
        matchup=row["matchup"],
        game_state=row.get("game_state") or "",
        side=row["side"],
        market_price_cents=int(row["current_ask_cents"]),
        model_probability_bps=int(round(float(row.get("model_probability_pct") or 0) * 100)),
        edge_bps=int(round(float(row.get("model_edge_pct") or 0) * 100)),
        opportunity_score=max(0, min(100, int(round(50 + float(row.get("model_edge_pct") or 0) * 3)))),
        signal=f"STRATEGY_V2_{code}",
    )
    trade = EdgePaperTrade.objects.create(
        user=user,
        signal=signal,
        side=row["side"],
        risk_cents=UNIT_RISK_CENTS,
        entry_price_cents=entry,
        status="OPEN",
    )
    EdgeAuditEvent.objects.create(user=user, event_type="EDGE_V2_OPEN", payload={
        "paper_trade_id": trade.id,
        "strategy_code": code,
        "source_strategy": row.get("source_strategy"),
        "ticker": ticker,
        "game_pk": game_pk,
        "risk_cents": UNIT_RISK_CENTS,
        "entry_price_cents": entry,
        "fingerprint": _fingerprint(row),
        "version": V2_VERSION,
    })
    return trade.id


def _close_trade(user, trade, exit_price, reason, extra=None):
    effective_exit = max(0.0, float(exit_price) - 0.5) if exit_price not in (0, 100) else float(exit_price)
    pnl = round(float(trade.risk_cents) * (effective_exit / float(trade.entry_price_cents) - 1.0))
    trade.exit_price_cents = int(exit_price)
    trade.pnl_cents = int(pnl)
    trade.status = "SETTLED" if reason == "FINAL_SETTLEMENT" else "EXITED"
    trade.closed_at = timezone.now()
    trade.save(update_fields=["exit_price_cents", "pnl_cents", "status", "closed_at"])
    payload = {
        "paper_trade_id": trade.id,
        "strategy_code": _code(trade),
        "ticker": _ticker(trade),
        "game_pk": _game_pk(trade),
        "exit_price_cents": int(exit_price),
        "exit_reason": reason,
        "pnl_cents": int(pnl),
        "version": V2_VERSION,
    }
    if extra:
        payload.update(extra)
    EdgeAuditEvent.objects.create(user=user, event_type="EDGE_V2_EXIT", payload=payload)
    return trade.id


def _winner_for_game(game):
    if not game or game.get("is_live"):
        return None
    status = str(game.get("status") or "").lower()
    if not any(word in status for word in ("final", "completed", "game over")):
        return None
    away = game.get("away") or {}
    home = game.get("home") or {}
    away_score = int(away.get("score") or 0)
    home_score = int(home.get("score") or 0)
    if away_score == home_score:
        return None
    return away.get("code") if away_score > home_score else home.get("code")


def _recover_event(user, trade):
    return EdgeAuditEvent.objects.filter(user=user, event_type="EDGE_V2_PRINCIPAL_RECOVERED", payload__paper_trade_id=trade.id).order_by("created_at").first()


def _manage_open_trades(user, board, all_signals):
    market_index, games = _market_index(board)
    actions = []
    rows = EdgePaperTrade.objects.filter(user=user, status="OPEN", signal__event_key__startswith="V2:").select_related("signal")
    now = timezone.now()
    for trade in rows:
        code = _code(trade)
        ticker = _ticker(trade)
        if code not in STRATEGIES or not ticker:
            continue
        market = market_index.get(ticker)
        game = games.get(_game_pk(trade))
        winner = _winner_for_game(game)
        side_code = str(trade.side or "").split(" ", 1)[0]

        if winner:
            won = side_code == winner
            if code == "X2R":
                recovered = _recover_event(user, trade)
                if recovered:
                    recover_price = float(recovered.payload.get("recover_price_cents") or 0)
                    contracts = float(trade.risk_cents) / float(trade.entry_price_cents)
                    half_contracts = contracts / 2.0
                    recovered_cash = half_contracts * recover_price
                    runner_cash = half_contracts * (100.0 if won else 0.0)
                    pnl = round(recovered_cash + runner_cash - float(trade.risk_cents))
                    trade.exit_price_cents = 100 if won else 0
                    trade.pnl_cents = int(pnl)
                    trade.status = "SETTLED"
                    trade.closed_at = now
                    trade.save(update_fields=["exit_price_cents", "pnl_cents", "status", "closed_at"])
                    EdgeAuditEvent.objects.create(user=user, event_type="EDGE_V2_EXIT", payload={
                        "paper_trade_id": trade.id, "strategy_code": code, "ticker": ticker, "game_pk": _game_pk(trade),
                        "exit_reason": "RECOVER_HALF_THEN_FINAL", "recover_price_cents": recover_price,
                        "winner": winner, "pnl_cents": int(pnl), "version": V2_VERSION,
                    })
                    actions.append(trade.id)
                    continue
            actions.append(_close_trade(user, trade, 100 if won else 0, "FINAL_SETTLEMENT", {"winner": winner}))
            continue

        if not market or market.get("bid_cents") is None:
            continue
        bid = int(market["bid_cents"])
        effective_bid = max(0.0, float(bid) - 0.5)
        entry = float(trade.entry_price_cents)

        if code == "R50" and effective_bid >= entry * 1.5:
            actions.append(_close_trade(user, trade, bid, "TARGET_1_50X"))
            continue
        if code == "X2" and effective_bid >= entry * 2.0:
            actions.append(_close_trade(user, trade, bid, "TARGET_2_00X"))
            continue
        if code == "X2R":
            if not _recover_event(user, trade) and effective_bid >= entry * 2.0:
                EdgeAuditEvent.objects.create(user=user, event_type="EDGE_V2_PRINCIPAL_RECOVERED", payload={
                    "paper_trade_id": trade.id,
                    "strategy_code": code,
                    "ticker": ticker,
                    "game_pk": _game_pk(trade),
                    "recover_price_cents": bid,
                    "contracts_sold_fraction": 0.5,
                    "version": V2_VERSION,
                })
                actions.append(trade.id)
            continue
        if code in ("DYN", "DYNRE"):
            current = all_signals.get(ticker) or {}
            current_edge = float(current.get("model_edge_pct") or 0)
            age = now - trade.created_at
            if effective_bid >= entry * 2.0:
                actions.append(_close_trade(user, trade, bid, "DYNAMIC_2X_TARGET"))
            elif current and current_edge <= 0:
                actions.append(_close_trade(user, trade, bid, "MODEL_EDGE_INVALIDATED", {"model_edge_pct": current_edge}))
            elif age >= timedelta(minutes=30):
                actions.append(_close_trade(user, trade, bid, "DYNAMIC_30M_MAX_HOLD", {"model_edge_pct": current_edge}))
    return actions


def run_v2_for_user(user, board=None):
    board = board or get_live_mlb_board()
    all_signals, qualifying = _signal_index()
    managed = _manage_open_trades(user, board, all_signals)
    opened = []
    skipped = []
    for row in qualifying:
        for code in STRATEGIES:
            allowed, reason = _can_open(user, code, row)
            if not allowed:
                skipped.append({"strategy_code": code, "ticker": row.get("ticker"), "reason": reason})
                continue
            opened.append(_open_trade(user, code, row))

    EdgeAuditEvent.objects.create(user=user, event_type="EDGE_V2_SERVER_TICK", payload={
        "version": V2_VERSION,
        "bankroll_cents_per_strategy": BANKROLL_CENTS,
        "unit_risk_cents": UNIT_RISK_CENTS,
        "opened_count": len(opened),
        "managed_count": len(managed),
        "qualifying_signal_count": len(qualifying),
    })
    return {"opened_count": len(opened), "managed_count": len(managed), "qualifying_signal_count": len(qualifying)}


def _trade_summary(trade):
    recovered = EdgeAuditEvent.objects.filter(event_type="EDGE_V2_PRINCIPAL_RECOVERED", payload__paper_trade_id=trade.id).order_by("created_at").first()
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
        "matchup": trade.signal.matchup if trade.signal else None,
        "game_state": trade.signal.game_state if trade.signal else None,
        "principal_recovered": bool(recovered),
        "principal_recovered_at": recovered.created_at if recovered else None,
        "recover_price_cents": recovered.payload.get("recover_price_cents") if recovered else None,
    }


def _summary(user, code):
    rows = list(_strategy_trades(user, code).order_by("-created_at")[:500])
    closed = [row for row in rows if row.status in ("EXITED", "SETTLED")]
    opened = [row for row in rows if row.status == "OPEN"]
    realized = sum(int(row.pnl_cents or 0) for row in closed)
    wins = sum(int(row.pnl_cents or 0) > 0 for row in closed)
    losses = sum(int(row.pnl_cents or 0) < 0 for row in closed)
    risk = sum(int(row.risk_cents or 0) for row in closed)
    roi = (100.0 * realized / risk) if risk else None
    return {
        "code": code,
        **STRATEGIES[code],
        "paper_bankroll_start_cents": BANKROLL_CENTS,
        "paper_equity_cents": BANKROLL_CENTS + realized,
        "realized_pnl_cents": realized,
        "roi_pct": round(roi, 2) if roi is not None else None,
        "trades": len(rows),
        "closed_trades": len(closed),
        "open_trades": len(opened),
        "open_risk_cents": sum(int(row.risk_cents or 0) for row in opened),
        "wins": wins,
        "losses": losses,
        "positive_trade_rate_pct": round(100.0 * wins / len(closed), 2) if closed else None,
        "recent_trades": [_trade_summary(row) for row in rows[:8]],
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def strategy_v2_scoreboard(request):
    strategies = [_summary(request.user, code) for code in STRATEGIES]
    ranked = [row for row in strategies if row["closed_trades"] > 0]
    ranked.sort(key=lambda row: (row["roi_pct"] if row["roi_pct"] is not None else -9999, row["closed_trades"]), reverse=True)
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    first_tick = EdgeAuditEvent.objects.filter(user=request.user, event_type="EDGE_V2_SERVER_TICK").order_by("created_at").first()
    last_tick = EdgeAuditEvent.objects.filter(user=request.user, event_type="EDGE_V2_SERVER_TICK").order_by("-created_at").first()
    return Response({
        "mode": "paper_only",
        "live_money_enabled": False,
        "version": V2_VERSION,
        "paper_bankroll_per_strategy_cents": BANKROLL_CENTS,
        "unit_risk_cents": UNIT_RISK_CENTS,
        "daily_max_risk_cents_per_strategy": DAILY_MAX_RISK_CENTS,
        "per_game_max_risk_cents_per_strategy": PER_GAME_MAX_RISK_CENTS,
        "experiment_start_at": first_tick.created_at if first_tick else None,
        "as_of": timezone.now(),
        "last_background_tick_at": last_tick.created_at if last_tick else None,
        "ranking_method": "realized ROI first; closed-trade count breaks ties",
        "leader": ranked[0]["code"] if ranked else None,
        "strategies": strategies,
        "research_note": "All v2 strategies consume the same PRIME feed and fixed $1 paper unit. The race changes exit and re-entry behavior only; no live exchange orders are created.",
    })
