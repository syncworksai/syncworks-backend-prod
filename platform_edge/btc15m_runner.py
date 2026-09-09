from __future__ import annotations

from datetime import timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import btc15m as base
from .models import EdgeAuditEvent, EdgePaperTrade, EdgeSignal, EdgeStrategy

RUNNER_VERSION = "BTC15M_EDGE_V1_1"


def _dt(value):
    parsed = parse_datetime(str(value or ""))
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, dt_timezone.utc)
    return parsed


def _market_by_ticker(ticker):
    payload = base._json_get(f"{base.KALSHI_BASE}/markets/{ticker}")
    return payload.get("market")


def _entry_decision_exists(user, ticker):
    return EdgeAuditEvent.objects.filter(
        user=user,
        event_type="BTC15M_DECISION",
        payload__ticker=ticker,
        payload__decision="ENTER",
    ).exists()


def _final_skip_exists(user, ticker):
    return EdgeAuditEvent.objects.filter(
        user=user,
        event_type="BTC15M_DECISION",
        payload__ticker=ticker,
        payload__decision="SKIP",
    ).exists()


def _settle_or_manage_existing(user, coinbase, fee_meta):
    closed = []
    trades = EdgePaperTrade.objects.filter(
        user=user,
        status="OPEN",
        signal__event_key__startswith="BTC15M:",
    ).select_related("signal")
    for trade in trades:
        ticker = str(trade.signal.event_key).split(":", 1)[1]
        try:
            market = _market_by_ticker(ticker)
            if not market:
                continue
            target = base._target_from_market(market)
            if not target:
                continue
            result = base._close_trade(user, trade, market, target, coinbase, fee_meta)
            if result.get("closed"):
                closed.append({"trade_id": trade.id, **result})
        except Exception as exc:
            EdgeAuditEvent.objects.create(
                user=user,
                event_type="BTC15M_RUNNER_ERROR",
                payload={"ticker": ticker, "phase": "close", "detail": str(exc)[:180], "runner_version": RUNNER_VERSION},
            )
    return closed


def _decision_payload(snapshot, decision, status):
    return {
        **snapshot,
        "runner_version": RUNNER_VERSION,
        "decision": status,
        "side": decision["side"],
        "fair_probability_pct": round(decision["fair"] * 100.0, 2),
        "edge_points": round(decision["edge"] * 100.0, 2),
        "spread_cents": round(decision["spread"] * 100.0, 2),
        "maker_target_cents": decision["maker_target_cents"],
        "checks": decision["checks"],
        "failed_checks": decision["failed_checks"],
    }


def _open_trade(user, ticker, target, seconds_remaining, snapshot, decision, fee_meta):
    ask = int(decision["ask_cents"])
    entry_fee = base._fee_cents(ask, base.RISK_CENTS, fee_meta["fee_multiplier"], maker=False)
    payload = _decision_payload(snapshot, decision, "ENTER")
    signal = EdgeSignal.objects.create(
        user=user,
        sport="BTC",
        event_key=f"BTC15M:{ticker}",
        matchup=f"BTC 15M • {ticker}",
        game_state=f"{round(seconds_remaining)}s remaining • target ${target:,.2f}",
        side=f"{decision['side']} YES",
        market_price_cents=ask,
        model_probability_bps=int(round(decision["fair"] * 10_000)),
        edge_bps=int(round(decision["edge"] * 10_000)),
        opportunity_score=max(0, min(100, int(round(50 + decision["edge"] * 500)))),
        signal=base.VERSION,
        max_entry_cents=min(99, int(round(decision["fair"] * 100 - base.MIN_EDGE * 100))),
    )
    trade = EdgePaperTrade.objects.create(
        user=user,
        signal=signal,
        side=f"{decision['side']} YES",
        risk_cents=base.RISK_CENTS,
        entry_price_cents=ask,
        status="OPEN",
    )
    EdgeAuditEvent.objects.create(user=user, event_type="BTC15M_DECISION", payload=payload)
    EdgeAuditEvent.objects.create(
        user=user,
        event_type="BTC15M_PAPER_OPEN",
        payload={
            **payload,
            "paper_trade_id": trade.id,
            "risk_cents": base.RISK_CENTS,
            "entry_price_cents": ask,
            "entry_fee_cents": entry_fee,
            "fee_assumption": "estimated_from_series_metadata",
            "execution_assumption": "executable_ask_taker_conservative",
            "paper_only": True,
        },
    )
    return trade


def run_for_user(user):
    start_event = base._experiment(user)
    fee_meta = base._series_fee_metadata()
    coinbase = base._coinbase_state()
    closed = _settle_or_manage_existing(user, coinbase, fee_meta)

    if not base._is_experiment_open(start_event):
        return {"experiment_open": False, "opened": 0, "closed": len(closed), "decision": "experiment_complete"}

    market = base._current_market()
    if not market:
        return {"experiment_open": True, "opened": 0, "closed": len(closed), "decision": "no_open_market"}

    ticker = market.get("ticker")
    close_at = _dt(market.get("close_time"))
    target = base._target_from_market(market)
    if not ticker or not close_at or not target:
        return {"experiment_open": True, "opened": 0, "closed": len(closed), "decision": "market_missing_target_or_time"}

    seconds_remaining = (close_at - timezone.now()).total_seconds()
    p_up = base._model_probability(target, coinbase, seconds_remaining)
    snapshot = base._snapshot_payload(market, target, coinbase, p_up, seconds_remaining, fee_meta)
    snapshot["runner_version"] = RUNNER_VERSION
    minute_key = timezone.now().strftime("%Y-%m-%dT%H:%M")
    if not EdgeAuditEvent.objects.filter(
        user=user,
        event_type="BTC15M_SNAPSHOT",
        payload__ticker=ticker,
        payload__minute_key=minute_key,
    ).exists():
        EdgeAuditEvent.objects.create(
            user=user,
            event_type="BTC15M_SNAPSHOT",
            payload={**snapshot, "minute_key": minute_key},
        )

    if base._open_trade_for_ticker(user, ticker):
        return {"experiment_open": True, "opened": 0, "closed": len(closed), "decision": "already_open", "snapshot": snapshot}
    if _entry_decision_exists(user, ticker):
        return {"experiment_open": True, "opened": 0, "closed": len(closed), "decision": "already_entered", "snapshot": snapshot}
    if _final_skip_exists(user, ticker):
        return {"experiment_open": True, "opened": 0, "closed": len(closed), "decision": "already_skipped", "snapshot": snapshot}

    if seconds_remaining > base.ENTRY_MAX_SECONDS:
        return {"experiment_open": True, "opened": 0, "closed": len(closed), "decision": "observing", "snapshot": snapshot}

    if seconds_remaining < base.ENTRY_MIN_SECONDS:
        latest_eval = EdgeAuditEvent.objects.filter(
            user=user,
            event_type="BTC15M_EVALUATION",
            payload__ticker=ticker,
        ).first()
        payload = dict(latest_eval.payload) if latest_eval else dict(snapshot)
        payload.update({
            "runner_version": RUNNER_VERSION,
            "decision": "SKIP",
            "reason": "entry_window_closed_without_qualified_setup",
            "failed_checks": payload.get("failed_checks") or ["no_qualified_setup_in_entry_window"],
        })
        EdgeAuditEvent.objects.create(user=user, event_type="BTC15M_DECISION", payload=payload)
        return {"experiment_open": True, "opened": 0, "closed": len(closed), "decision": "final_skip", "snapshot": snapshot}

    decision = base._decision(snapshot)
    evaluation = _decision_payload(snapshot, decision, "QUALIFIED" if decision["qualifies"] else "WATCH")
    if not EdgeAuditEvent.objects.filter(
        user=user,
        event_type="BTC15M_EVALUATION",
        payload__ticker=ticker,
        payload__minute_key=minute_key,
    ).exists():
        EdgeAuditEvent.objects.create(
            user=user,
            event_type="BTC15M_EVALUATION",
            payload={**evaluation, "minute_key": minute_key},
        )

    if not decision["qualifies"]:
        return {
            "experiment_open": True,
            "opened": 0,
            "closed": len(closed),
            "decision": "watch",
            "snapshot": snapshot,
            "failed_checks": decision["failed_checks"],
        }

    trade = _open_trade(user, ticker, target, seconds_remaining, snapshot, decision, fee_meta)
    return {
        "experiment_open": True,
        "opened": 1,
        "closed": len(closed),
        "decision": "entered",
        "trade_id": trade.id,
        "snapshot": snapshot,
    }


def _eligible_users():
    strategy_ids = EdgeStrategy.objects.values_list("user_id", flat=True)
    experiment_ids = EdgeAuditEvent.objects.filter(event_type="BTC15M_EXPERIMENT_STARTED").values_list("user_id", flat=True)
    ids = set(strategy_ids).union(experiment_ids)
    return get_user_model().objects.filter(id__in=ids, is_active=True)


@api_view(["POST"])
@permission_classes([AllowAny])
def system_btc15m_tick(request):
    results = []
    for user in _eligible_users():
        try:
            results.append(run_for_user(user))
        except Exception as exc:
            results.append({"error": True, "detail": str(exc)[:180]})
    return Response({
        "mode": "paper_only",
        "live_money_enabled": False,
        "version": RUNNER_VERSION,
        "ran_at": timezone.now(),
        "users_processed": len(results),
        "opened_count": sum(int(row.get("opened") or 0) for row in results),
        "closed_count": sum(int(row.get("closed") or 0) for row in results),
        "errors": [row for row in results if row.get("error")],
    })


btc15m_dashboard = base.btc15m_dashboard
