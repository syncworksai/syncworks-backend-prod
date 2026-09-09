from __future__ import annotations

import math
import re
import statistics
from datetime import timedelta
from urllib.parse import quote

import requests
from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import EdgeAuditEvent, EdgePaperTrade, EdgeSignal, EdgeStrategy

KALSHI_BASE = "https://external-api.kalshi.com/trade-api/v2"
COINBASE_CANDLES = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
SERIES_TICKER = "KXBTC15M"
VERSION = "BTC15M_EDGE_V1"
START_BANKROLL_CENTS = 10_000
RISK_CENTS = 100
EXPERIMENT_DAYS = 7
ENTRY_MIN_SECONDS = 120
ENTRY_MAX_SECONDS = 300
MIN_FAIR_PROBABILITY = 0.75
MIN_EDGE = 0.05
MAX_SPREAD = 0.03
MIN_ENTRY_PRICE = 0.15
MAX_ENTRY_PRICE = 0.93
REQUEST_TIMEOUT = 8


def _json_get(url, params=None):
    response = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "SyncWorks-EDGE-BTC15M/1.0"},
    )
    response.raise_for_status()
    return response.json()


def _dt(value):
    parsed = parse_datetime(str(value or ""))
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.utc)
    return parsed


def _cents(value):
    if value in (None, ""):
        return None
    try:
        return int(round(float(value) * 100))
    except (TypeError, ValueError):
        return None


def _target_from_market(market):
    for key in ("floor_strike", "cap_strike"):
        try:
            value = float(market.get(key))
            if value > 1000:
                return value
        except (TypeError, ValueError):
            pass

    text = " ".join(
        str(market.get(key) or "")
        for key in ("yes_sub_title", "no_sub_title", "subtitle", "title", "functional_strike", "rules_primary")
    )
    candidates = re.findall(r"\$?\s*([0-9]{2,3}(?:,[0-9]{3})+(?:\.[0-9]+)?)", text)
    values = []
    for candidate in candidates:
        try:
            value = float(candidate.replace(",", ""))
            if value > 1000:
                values.append(value)
        except ValueError:
            continue
    return values[0] if values else None


def _market_prices(market):
    return {
        "yes_bid_cents": _cents(market.get("yes_bid_dollars")),
        "yes_ask_cents": _cents(market.get("yes_ask_dollars")),
        "no_bid_cents": _cents(market.get("no_bid_dollars")),
        "no_ask_cents": _cents(market.get("no_ask_dollars")),
    }


def _current_market():
    payload = _json_get(
        f"{KALSHI_BASE}/markets",
        params={"series_ticker": SERIES_TICKER, "status": "open", "limit": 50},
    )
    now = timezone.now()
    candidates = []
    for market in payload.get("markets", []):
        close_at = _dt(market.get("close_time"))
        if not close_at or close_at <= now:
            continue
        seconds = (close_at - now).total_seconds()
        if seconds <= 20 * 60:
            candidates.append((close_at, market))
    if not candidates:
        return None
    candidates.sort(key=lambda row: row[0])
    return candidates[0][1]


def _market_by_ticker(ticker):
    payload = _json_get(f"{KALSHI_BASE}/markets", params={"tickers": ticker, "limit": 1})
    markets = payload.get("markets", [])
    return markets[0] if markets else None


def _series_fee_metadata():
    try:
        payload = _json_get(f"{KALSHI_BASE}/series/{SERIES_TICKER}")
        series = payload.get("series") or {}
        return {
            "fee_type": series.get("fee_type") or "quadratic",
            "fee_multiplier": float(series.get("fee_multiplier") if series.get("fee_multiplier") is not None else 1.0),
        }
    except Exception:
        return {"fee_type": "quadratic", "fee_multiplier": 1.0}


def _coinbase_state():
    rows = _json_get(COINBASE_CANDLES, params={"granularity": 60})
    candles = []
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        try:
            candles.append((int(row[0]), float(row[4])))
        except (TypeError, ValueError):
            continue
    candles.sort(key=lambda row: row[0])
    closes = [row[1] for row in candles[-40:]]
    if len(closes) < 16:
        raise ValueError("Coinbase returned too few one-minute candles")

    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    sigma = statistics.pstdev(log_returns[-30:]) if len(log_returns) >= 2 else 0.0
    sigma = max(0.00012, sigma)
    spot = closes[-1]
    ret1 = spot / closes[-2] - 1.0
    ret5 = spot / closes[-6] - 1.0
    ret15 = spot / closes[-16] - 1.0
    return {
        "spot": spot,
        "ret1": ret1,
        "ret5": ret5,
        "ret15": ret15,
        "sigma_1m": sigma,
        "candle_ts": candles[-1][0],
    }


def _normal_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _clip(value, low, high):
    return max(low, min(high, value))


def _logit(p):
    p = _clip(p, 0.001, 0.999)
    return math.log(p / (1.0 - p))


def _sigmoid(x):
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _model_probability(target, coinbase, seconds_remaining):
    spot = coinbase["spot"]
    sigma = coinbase["sigma_1m"]
    minutes = max(seconds_remaining / 60.0, 0.35)
    distance = math.log(max(1.0, spot) / max(1.0, target))
    z = distance / max(1e-9, sigma * math.sqrt(minutes))
    base = _clip(_normal_cdf(z), 0.02, 0.98)

    mom1_z = _clip(coinbase["ret1"] / sigma, -2.5, 2.5)
    mom5_z = _clip(coinbase["ret5"] / (sigma * math.sqrt(5.0)), -2.5, 2.5)
    adjusted = _sigmoid(_logit(base) + 0.35 * mom1_z + 0.25 * mom5_z)
    return _clip(adjusted, 0.02, 0.98)


def _fee_cents(price_cents, risk_cents, fee_multiplier, maker=False):
    if not price_cents or price_cents <= 0 or risk_cents <= 0:
        return 0
    price = price_cents / 100.0
    contracts = (risk_cents / 100.0) / price
    rate = 0.0175 if maker else 0.07
    raw_dollars = max(0.0, fee_multiplier) * rate * contracts * price * (1.0 - price)
    # Conservative paper assumption: round each modeled fill up to the next whole cent.
    return int(math.ceil(raw_dollars * 100.0 - 1e-12))


def _experiment(user):
    event = EdgeAuditEvent.objects.filter(user=user, event_type="BTC15M_EXPERIMENT_STARTED").order_by("created_at").first()
    if event:
        return event
    return EdgeAuditEvent.objects.create(
        user=user,
        event_type="BTC15M_EXPERIMENT_STARTED",
        payload={
            "version": VERSION,
            "paper_only": True,
            "start_bankroll_cents": START_BANKROLL_CENTS,
            "risk_cents_per_trade": RISK_CENTS,
            "planned_days": EXPERIMENT_DAYS,
            "entry_window_seconds": [ENTRY_MIN_SECONDS, ENTRY_MAX_SECONDS],
            "minimum_fair_probability_pct": MIN_FAIR_PROBABILITY * 100,
            "minimum_edge_pct_points": MIN_EDGE * 100,
            "max_spread_cents": MAX_SPREAD * 100,
            "execution_assumption": "executable_ask_taker_conservative",
        },
    )


def _is_experiment_open(start_event):
    return timezone.now() < start_event.created_at + timedelta(days=EXPERIMENT_DAYS)


def _open_trade_for_ticker(user, ticker):
    return EdgePaperTrade.objects.filter(
        user=user,
        status="OPEN",
        signal__event_key=f"BTC15M:{ticker}",
    ).select_related("signal").first()


def _decision_exists(user, ticker):
    return EdgeAuditEvent.objects.filter(
        user=user,
        event_type="BTC15M_DECISION",
        payload__ticker=ticker,
    ).exists()


def _snapshot_payload(market, target, coinbase, p_up, seconds_remaining, fee_meta):
    prices = _market_prices(market)
    up_edge = (p_up * 100.0 - (prices["yes_ask_cents"] or 100)) if prices["yes_ask_cents"] is not None else None
    p_down = 1.0 - p_up
    down_edge = (p_down * 100.0 - (prices["no_ask_cents"] or 100)) if prices["no_ask_cents"] is not None else None
    return {
        "version": VERSION,
        "ticker": market.get("ticker"),
        "close_time": market.get("close_time"),
        "seconds_remaining": round(seconds_remaining),
        "target": round(target, 2),
        "btc_spot": round(coinbase["spot"], 2),
        "ret1_pct": round(coinbase["ret1"] * 100.0, 4),
        "ret5_pct": round(coinbase["ret5"] * 100.0, 4),
        "ret15_pct": round(coinbase["ret15"] * 100.0, 4),
        "realized_vol_1m_pct": round(coinbase["sigma_1m"] * 100.0, 4),
        "model_up_pct": round(p_up * 100.0, 2),
        "model_down_pct": round(p_down * 100.0, 2),
        "up_edge_points": round(up_edge, 2) if up_edge is not None else None,
        "down_edge_points": round(down_edge, 2) if down_edge is not None else None,
        **prices,
        **fee_meta,
        "source_note": "Coinbase BTC/USD is the live signal proxy; Kalshi settlement remains governed by the contract's stated benchmark.",
    }


def _decision(snapshot):
    p_up = float(snapshot["model_up_pct"]) / 100.0
    side = "UP" if p_up >= 0.5 else "DOWN"
    fair = p_up if side == "UP" else 1.0 - p_up
    ask = snapshot["yes_ask_cents"] if side == "UP" else snapshot["no_ask_cents"]
    bid = snapshot["yes_bid_cents"] if side == "UP" else snapshot["no_bid_cents"]
    ret1 = float(snapshot["ret1_pct"])
    ret5 = float(snapshot["ret5_pct"])
    target = float(snapshot["target"])
    spot = float(snapshot["btc_spot"])

    momentum_ok = (ret1 > 0 and ret5 > 0) if side == "UP" else (ret1 < 0 and ret5 < 0)
    target_ok = spot > target if side == "UP" else spot < target
    spread = (ask - bid) / 100.0 if ask is not None and bid is not None else 1.0
    edge = fair - (ask / 100.0) if ask is not None else -1.0
    price_ok = ask is not None and int(MIN_ENTRY_PRICE * 100) <= ask <= int(MAX_ENTRY_PRICE * 100)

    checks = {
        "fair_probability": fair >= MIN_FAIR_PROBABILITY,
        "edge": edge >= MIN_EDGE,
        "momentum": momentum_ok,
        "persistent_side_of_target": target_ok,
        "spread": spread <= MAX_SPREAD,
        "entry_price": price_ok,
    }
    qualifies = all(checks.values())
    maker_target = min(ask, (bid + 1) if bid is not None else ask) if ask is not None else None
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "qualifies": qualifies,
        "side": side,
        "fair": fair,
        "ask_cents": ask,
        "bid_cents": bid,
        "maker_target_cents": maker_target,
        "edge": edge,
        "spread": spread,
        "checks": checks,
        "failed_checks": failed,
    }


def _close_trade(user, trade, market, target, coinbase, fee_meta):
    prices = _market_prices(market)
    result = str(market.get("result") or "").lower()
    side = "UP" if str(trade.side).startswith("UP") else "DOWN"
    wanted_result = "yes" if side == "UP" else "no"
    entry_fee = int((EdgeAuditEvent.objects.filter(
        user=user,
        event_type="BTC15M_PAPER_OPEN",
        payload__paper_trade_id=trade.id,
    ).first() or EdgeAuditEvent(payload={})).payload.get("entry_fee_cents") or 0)

    if result in ("yes", "no"):
        won = result == wanted_result
        pnl = round(trade.risk_cents * (100.0 / trade.entry_price_cents - 1.0)) - entry_fee if won else -int(trade.risk_cents) - entry_fee
        trade.exit_price_cents = 100 if won else 0
        trade.pnl_cents = pnl
        trade.status = "SETTLED"
        trade.closed_at = timezone.now()
        trade.save(update_fields=["exit_price_cents", "pnl_cents", "status", "closed_at"])
        EdgeAuditEvent.objects.create(user=user, event_type="BTC15M_PAPER_EXIT", payload={
            "version": VERSION,
            "paper_trade_id": trade.id,
            "ticker": market.get("ticker"),
            "side": side,
            "exit_reason": "KALSHI_SETTLEMENT",
            "result": result,
            "won": won,
            "entry_fee_cents": entry_fee,
            "exit_fee_cents": 0,
            "pnl_cents": pnl,
        })
        return {"closed": True, "reason": "settled", "pnl_cents": pnl}

    close_at = _dt(market.get("close_time"))
    if close_at and close_at <= timezone.now():
        return {"closed": False, "reason": "awaiting_settlement"}

    seconds_remaining = max(1.0, (close_at - timezone.now()).total_seconds()) if close_at else 60.0
    p_up = _model_probability(target, coinbase, seconds_remaining)
    fair = p_up if side == "UP" else 1.0 - p_up
    bid = prices["yes_bid_cents"] if side == "UP" else prices["no_bid_cents"]
    if bid is None:
        return {"closed": False, "reason": "no_bid"}

    ret1 = coinbase["ret1"]
    spot = coinbase["spot"]
    thesis_broken = fair < 0.55 or ((side == "UP" and ret1 < 0 and spot < target) or (side == "DOWN" and ret1 > 0 and spot > target))
    market_over_fair = (bid / 100.0) >= fair + 0.01
    if not thesis_broken and not market_over_fair:
        return {"closed": False, "reason": "hold"}

    exit_fee = _fee_cents(bid, trade.risk_cents, fee_meta["fee_multiplier"], maker=False)
    pnl = round(trade.risk_cents * (bid / trade.entry_price_cents - 1.0)) - entry_fee - exit_fee
    trade.exit_price_cents = bid
    trade.pnl_cents = pnl
    trade.status = "EXITED"
    trade.closed_at = timezone.now()
    trade.save(update_fields=["exit_price_cents", "pnl_cents", "status", "closed_at"])
    reason = "MARKET_AT_OR_ABOVE_MODEL_FAIR" if market_over_fair else "THESIS_BROKEN"
    EdgeAuditEvent.objects.create(user=user, event_type="BTC15M_PAPER_EXIT", payload={
        "version": VERSION,
        "paper_trade_id": trade.id,
        "ticker": market.get("ticker"),
        "side": side,
        "exit_reason": reason,
        "model_fair_pct": round(fair * 100.0, 2),
        "exit_price_cents": bid,
        "entry_fee_cents": entry_fee,
        "exit_fee_cents": exit_fee,
        "pnl_cents": pnl,
    })
    return {"closed": True, "reason": reason, "pnl_cents": pnl}


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
            target = _target_from_market(market)
            if not target:
                continue
            result = _close_trade(user, trade, market, target, coinbase, fee_meta)
            if result.get("closed"):
                closed.append({"trade_id": trade.id, **result})
        except Exception as exc:
            EdgeAuditEvent.objects.create(user=user, event_type="BTC15M_RUNNER_ERROR", payload={"ticker": ticker, "phase": "close", "detail": str(exc)[:180]})
    return closed


def run_for_user(user):
    start_event = _experiment(user)
    fee_meta = _series_fee_metadata()
    coinbase = _coinbase_state()
    closed = _settle_or_manage_existing(user, coinbase, fee_meta)

    if not _is_experiment_open(start_event):
        return {"experiment_open": False, "opened": 0, "closed": len(closed), "decision": None}

    market = _current_market()
    if not market:
        return {"experiment_open": True, "opened": 0, "closed": len(closed), "decision": "no_open_market"}

    ticker = market.get("ticker")
    close_at = _dt(market.get("close_time"))
    target = _target_from_market(market)
    if not ticker or not close_at or not target:
        return {"experiment_open": True, "opened": 0, "closed": len(closed), "decision": "market_missing_target_or_time"}

    seconds_remaining = (close_at - timezone.now()).total_seconds()
    p_up = _model_probability(target, coinbase, seconds_remaining)
    snapshot = _snapshot_payload(market, target, coinbase, p_up, seconds_remaining, fee_meta)
    minute_key = timezone.now().strftime("%Y-%m-%dT%H:%M")
    if not EdgeAuditEvent.objects.filter(user=user, event_type="BTC15M_SNAPSHOT", payload__ticker=ticker, payload__minute_key=minute_key).exists():
        EdgeAuditEvent.objects.create(user=user, event_type="BTC15M_SNAPSHOT", payload={**snapshot, "minute_key": minute_key})

    if _open_trade_for_ticker(user, ticker):
        return {"experiment_open": True, "opened": 0, "closed": len(closed), "decision": "already_open", "snapshot": snapshot}
    if _decision_exists(user, ticker):
        return {"experiment_open": True, "opened": 0, "closed": len(closed), "decision": "already_decided", "snapshot": snapshot}
    if seconds_remaining > ENTRY_MAX_SECONDS:
        return {"experiment_open": True, "opened": 0, "closed": len(closed), "decision": "observing", "snapshot": snapshot}

    if seconds_remaining < ENTRY_MIN_SECONDS:
        EdgeAuditEvent.objects.create(user=user, event_type="BTC15M_DECISION", payload={
            **snapshot,
            "decision": "SKIP",
            "reason": "entry_window_missed",
            "failed_checks": ["entry_window"],
        })
        return {"experiment_open": True, "opened": 0, "closed": len(closed), "decision": "skip_entry_window", "snapshot": snapshot}

    decision = _decision(snapshot)
    decision_payload = {
        **snapshot,
        "decision": "ENTER" if decision["qualifies"] else "SKIP",
        "side": decision["side"],
        "fair_probability_pct": round(decision["fair"] * 100.0, 2),
        "edge_points": round(decision["edge"] * 100.0, 2),
        "spread_cents": round(decision["spread"] * 100.0, 2),
        "maker_target_cents": decision["maker_target_cents"],
        "checks": decision["checks"],
        "failed_checks": decision["failed_checks"],
    }
    EdgeAuditEvent.objects.create(user=user, event_type="BTC15M_DECISION", payload=decision_payload)

    if not decision["qualifies"]:
        return {"experiment_open": True, "opened": 0, "closed": len(closed), "decision": "skip", "snapshot": snapshot, "failed_checks": decision["failed_checks"]}

    ask = int(decision["ask_cents"])
    entry_fee = _fee_cents(ask, RISK_CENTS, fee_meta["fee_multiplier"], maker=False)
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
        signal=VERSION,
        max_entry_cents=min(99, int(round(decision["fair"] * 100 - MIN_EDGE * 100))),
    )
    trade = EdgePaperTrade.objects.create(
        user=user,
        signal=signal,
        side=f"{decision['side']} YES",
        risk_cents=RISK_CENTS,
        entry_price_cents=ask,
        status="OPEN",
    )
    EdgeAuditEvent.objects.create(user=user, event_type="BTC15M_PAPER_OPEN", payload={
        **decision_payload,
        "paper_trade_id": trade.id,
        "risk_cents": RISK_CENTS,
        "entry_price_cents": ask,
        "entry_fee_cents": entry_fee,
        "execution_assumption": "executable_ask_taker_conservative",
        "paper_only": True,
    })
    return {"experiment_open": True, "opened": 1, "closed": len(closed), "decision": "entered", "trade_id": trade.id, "snapshot": snapshot}


def _eligible_users():
    ids = EdgeStrategy.objects.values_list("user_id", flat=True).distinct()
    return get_user_model().objects.filter(id__in=ids, is_active=True)


def _trade_rows(user, start_at):
    trades = EdgePaperTrade.objects.filter(
        user=user,
        created_at__gte=start_at,
        signal__event_key__startswith="BTC15M:",
    ).select_related("signal").order_by("created_at")
    return list(trades)


def _summary_for_user(user):
    start_event = _experiment(user)
    end_at = start_event.created_at + timedelta(days=EXPERIMENT_DAYS)
    trades = _trade_rows(user, start_event.created_at)
    decisions = list(EdgeAuditEvent.objects.filter(
        user=user,
        event_type="BTC15M_DECISION",
        created_at__gte=start_event.created_at,
    ).order_by("-created_at")[:1000])
    latest_snapshot = EdgeAuditEvent.objects.filter(
        user=user,
        event_type="BTC15M_SNAPSHOT",
        created_at__gte=start_event.created_at,
    ).first()

    closed = [trade for trade in trades if trade.status in ("EXITED", "SETTLED")]
    realized = sum(int(trade.pnl_cents or 0) for trade in closed)
    wins = sum(int(trade.pnl_cents or 0) > 0 for trade in closed)
    losses = sum(int(trade.pnl_cents or 0) < 0 for trade in closed)
    open_count = sum(trade.status == "OPEN" for trade in trades)
    entries = len(trades)
    skips = sum(event.payload.get("decision") == "SKIP" for event in decisions)

    equity = START_BANKROLL_CENTS
    curve = [{"at": start_event.created_at, "equity_cents": equity, "pnl_cents": 0}]
    for trade in sorted(closed, key=lambda row: row.closed_at or row.created_at):
        equity += int(trade.pnl_cents or 0)
        curve.append({"at": trade.closed_at or trade.created_at, "equity_cents": equity, "pnl_cents": int(trade.pnl_cents or 0)})

    trade_by_ticker = {str(trade.signal.event_key).split(":", 1)[1]: trade for trade in trades if trade.signal}
    recent_sessions = []
    for event in decisions[:40]:
        ticker = event.payload.get("ticker")
        trade = trade_by_ticker.get(ticker)
        recent_sessions.append({
            "at": event.created_at,
            "ticker": ticker,
            "decision": event.payload.get("decision"),
            "side": event.payload.get("side"),
            "target": event.payload.get("target"),
            "btc_spot": event.payload.get("btc_spot"),
            "fair_probability_pct": event.payload.get("fair_probability_pct"),
            "edge_points": event.payload.get("edge_points"),
            "market_ask_cents": event.payload.get("yes_ask_cents") if event.payload.get("side") == "UP" else event.payload.get("no_ask_cents"),
            "maker_target_cents": event.payload.get("maker_target_cents"),
            "failed_checks": event.payload.get("failed_checks") or [],
            "trade_status": trade.status if trade else None,
            "entry_price_cents": trade.entry_price_cents if trade else None,
            "exit_price_cents": trade.exit_price_cents if trade else None,
            "pnl_cents": trade.pnl_cents if trade and trade.status in ("EXITED", "SETTLED") else None,
        })

    positive_rate = (wins / len(closed) * 100.0) if closed else 0.0
    roi = (realized / START_BANKROLL_CENTS * 100.0) if START_BANKROLL_CENTS else 0.0
    avg_edge = statistics.mean([
        float(event.payload.get("edge_points"))
        for event in decisions
        if event.payload.get("decision") == "ENTER" and event.payload.get("edge_points") is not None
    ]) if any(event.payload.get("decision") == "ENTER" and event.payload.get("edge_points") is not None for event in decisions) else 0.0

    return {
        "mode": "paper_only",
        "live_money_enabled": False,
        "version": VERSION,
        "experiment": {
            "started_at": start_event.created_at,
            "ends_at": end_at,
            "active": timezone.now() < end_at,
            "planned_days": EXPERIMENT_DAYS,
            "potential_15m_windows": EXPERIMENT_DAYS * 24 * 4,
            "start_bankroll_cents": START_BANKROLL_CENTS,
            "risk_cents_per_trade": RISK_CENTS,
        },
        "metrics": {
            "equity_cents": START_BANKROLL_CENTS + realized,
            "net_pnl_cents": realized,
            "roi_pct": round(roi, 2),
            "sessions_evaluated": len(decisions),
            "entries": entries,
            "skips": skips,
            "open_trades": open_count,
            "closed_trades": len(closed),
            "wins": wins,
            "losses": losses,
            "positive_close_rate_pct": round(positive_rate, 2),
            "avg_entry_edge_points": round(avg_edge, 2),
        },
        "rules": {
            "entry_window": "T-5:00 to T-2:00",
            "minimum_model_probability_pct": MIN_FAIR_PROBABILITY * 100,
            "minimum_edge_points": MIN_EDGE * 100,
            "max_spread_cents": MAX_SPREAD * 100,
            "entry_price_range_cents": [int(MIN_ENTRY_PRICE * 100), int(MAX_ENTRY_PRICE * 100)],
            "momentum_confirmation": "1m and 5m returns must agree with side",
            "exit": "market at/above model fair value, thesis break, or settlement",
            "execution": "conservative executable ask; maker target shown but not assumed filled",
            "stake": "$1 fixed per qualifying 15-minute window; no compounding during test",
        },
        "current_session": ({"observed_at": latest_snapshot.created_at, **latest_snapshot.payload} if latest_snapshot else None),
        "equity_curve": curve,
        "recent_sessions": recent_sessions,
    }


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
        "version": VERSION,
        "ran_at": timezone.now(),
        "users_processed": len(results),
        "opened_count": sum(int(row.get("opened") or 0) for row in results),
        "closed_count": sum(int(row.get("closed") or 0) for row in results),
        "errors": [row for row in results if row.get("error")],
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def btc15m_dashboard(request):
    try:
        return Response(_summary_for_user(request.user))
    except Exception as exc:
        return Response({"detail": f"BTC 15m paper dashboard unavailable: {str(exc)[:180]}"}, status=503)
