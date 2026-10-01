from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from statistics import median

from django.db.models import Sum
from django.utils import timezone

from user_accounts.models.personal_finance import (
    FinanceAccount,
    FinanceBudget,
    FinanceConnection,
    FinanceGoal,
    FinanceLiability,
    FinanceObligation,
    FinanceTransaction,
)

ZERO = Decimal("0")
CENT = Decimal("0.01")


def _decimal(value, default=ZERO):
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _merchant_key(transaction: FinanceTransaction) -> str:
    raw = transaction.merchant_name or transaction.description or ""
    value = re.sub(r"[^A-Z0-9 ]+", " ", raw.upper())
    return re.sub(r"\s+", " ", value).strip()[:120]


def _cadence_for_intervals(intervals: list[int]) -> tuple[str, int] | None:
    if not intervals:
        return None
    days = int(round(float(median(intervals))))
    if 5 <= days <= 10:
        return "WEEKLY", 7
    if 11 <= days <= 18:
        return "BIWEEKLY", 14
    if 20 <= days <= 40:
        return "MONTHLY", 30
    if 50 <= days <= 75:
        return "BIMONTHLY", 60
    if 75 <= days <= 105:
        return "QUARTERLY", 90
    return None


def infer_recurring_obligations(user, lookback_days: int = 180) -> dict:
    cutoff = timezone.localdate() - timedelta(days=lookback_days)
    transactions = list(
        FinanceTransaction.objects.filter(
            user=user,
            date__gte=cutoff,
            amount__gt=0,
            is_transfer=False,
        ).order_by("date", "id")
    )
    grouped: dict[str, list[FinanceTransaction]] = defaultdict(list)
    for transaction in transactions:
        key = _merchant_key(transaction)
        if key:
            grouped[key].append(transaction)

    created = updated = candidates = 0
    for key, rows in grouped.items():
        if len(rows) < 2:
            continue
        intervals = [(rows[index].date - rows[index - 1].date).days for index in range(1, len(rows))]
        cadence = _cadence_for_intervals(intervals)
        if not cadence:
            continue
        cadence_name, cadence_days = cadence
        amounts = [row.amount for row in rows if row.amount is not None]
        if not amounts:
            continue
        candidates += 1
        expected_amount = Decimal(str(median(amounts))).quantize(CENT)
        latest = rows[-1]
        display_name = latest.merchant_name or latest.description or key.title()
        if FinanceObligation.objects.filter(
            user=user,
            is_manual=True,
            name__iexact=display_name,
            active=True,
        ).exists():
            continue
        _, was_created = FinanceObligation.objects.update_or_create(
            user=user,
            provider_stream_id=f"SYNC-INFERRED:{key}",
            defaults={
                "name": display_name[:180],
                "merchant": display_name[:180],
                "category": FinanceObligation.Category.SUBSCRIPTIONS,
                "expected_amount": expected_amount,
                "next_due_date": latest.date + timedelta(days=cadence_days),
                "cadence": cadence_name,
                "recurring": True,
                "active": True,
                "is_manual": False,
                "metadata": {
                    "source": "syncworks_recurring_inference",
                    "sample_count": len(rows),
                    "median_interval_days": int(round(float(median(intervals)))) if intervals else None,
                    "latest_transaction_id": latest.id,
                },
            },
        )
        created += int(was_created)
        updated += int(not was_created)
    return {
        "transactions_scanned": len(transactions),
        "recurring_candidates": candidates,
        "created": created,
        "updated": updated,
    }


def _liability_apr(item: FinanceLiability):
    if item.apr is not None:
        return item.apr
    if item.interest_rate is not None:
        return item.interest_rate
    return None


def _credit_limit(item: FinanceLiability):
    if item.account_id and getattr(item, "account", None) is not None and item.account.credit_limit is not None:
        return item.account.credit_limit
    metadata = item.metadata or {}
    return _decimal(metadata.get("credit_limit"), None)


def _promo_end(item: FinanceLiability):
    raw = (item.metadata or {}).get("promo_apr_end_date")
    if not raw:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def _dollars_to_utilization(balance: Decimal, limit: Decimal | None, target_pct: int):
    if not limit or limit <= 0:
        return None
    target_balance = (limit * Decimal(target_pct) / Decimal("100")).quantize(CENT)
    return max(ZERO, balance - target_balance).quantize(CENT)


def _debt_row(item: FinanceLiability, rank: int | None = None, owner_labels: dict[int, str] | None = None) -> dict:
    balance = item.outstanding_balance or ZERO
    limit = _credit_limit(item)
    apr = _liability_apr(item)
    minimum = item.minimum_payment if item.minimum_payment is not None else item.next_payment_amount
    utilization = float((balance / limit) * 100) if limit and limit > 0 else None
    promo_end = _promo_end(item)
    owner_labels = owner_labels or {}
    owner_name = owner_labels.get(item.user_id, "")
    return {
        "rank": rank,
        "id": item.id,
        "user_id": item.user_id,
        "owner_name": owner_name,
        "name": item.name,
        "kind": item.kind,
        "balance": balance,
        "apr": apr,
        "minimum_payment": minimum,
        "credit_limit": limit,
        "utilization_percent": round(utilization, 1) if utilization is not None else None,
        "to_70_percent": _dollars_to_utilization(balance, limit, 70),
        "to_50_percent": _dollars_to_utilization(balance, limit, 50),
        "to_30_percent": _dollars_to_utilization(balance, limit, 30),
        "promo_apr_end_date": promo_end,
        "account_status": (item.metadata or {}).get("account_status", ""),
        "paid_this_cycle": bool((item.metadata or {}).get("paid_this_cycle", False)),
    }


def build_debt_plan_1(
    liabilities,
    *,
    extra_monthly=ZERO,
    owner_labels: dict[int, str] | None = None,
) -> dict:
    """Build a conservative, explainable first debt plan.

    Plan 1 protects every known minimum, closes a very small high-interest balance
    first when one exists, then follows APR order. Debts with missing APR/minimum
    data stay visible but are not silently treated as low priority.
    """
    today = timezone.localdate()
    extra_monthly = max(ZERO, _decimal(extra_monthly))
    items = [item for item in liabilities if (item.outstanding_balance or ZERO) > 0]
    rows = [_debt_row(item, owner_labels=owner_labels) for item in items]

    known_minimums = sum((_decimal(row["minimum_payment"]) for row in rows if row["minimum_payment"] is not None), ZERO)
    total_debt = sum((_decimal(row["balance"]) for row in rows), ZERO)

    missing_data = []
    for row in rows:
        missing = []
        if row["apr"] is None:
            missing.append("APR")
        if row["minimum_payment"] is None:
            missing.append("minimum payment")
        if row["kind"] == FinanceLiability.Kind.CREDIT_CARD and row["credit_limit"] is None:
            missing.append("credit limit")
        if missing:
            missing_data.append({
                "id": row["id"],
                "name": row["name"],
                "owner_name": row["owner_name"],
                "missing": missing,
            })

    known_interest = [row for row in rows if row["apr"] is not None and _decimal(row["apr"]) > 0]
    zero_interest = [row for row in rows if row["apr"] is not None and _decimal(row["apr"]) <= 0]
    unknown_apr = [row for row in rows if row["apr"] is None]

    quick_wins = [
        row for row in known_interest
        if _decimal(row["balance"]) <= Decimal("500") and _decimal(row["apr"]) >= Decimal("20")
    ]
    quick_win = sorted(
        quick_wins,
        key=lambda row: (-float(_decimal(row["apr"])), float(_decimal(row["balance"]))),
    )[0] if quick_wins else None

    interest_order = sorted(
        known_interest,
        key=lambda row: (-float(_decimal(row["apr"])), float(_decimal(row["balance"]))),
    )
    priority = []
    if quick_win:
        priority.append(quick_win)
    priority.extend(row for row in interest_order if not quick_win or row["id"] != quick_win["id"])
    priority.extend(sorted(unknown_apr, key=lambda row: float(_decimal(row["balance"]))))
    priority.extend(sorted(zero_interest, key=lambda row: float(_decimal(row["balance"]))))

    for index, row in enumerate(priority, 1):
        row["rank"] = index
        if row["apr"] is None:
            row["priority_reason"] = "Needs APR before SyncWorks can safely rank extra payments."
        elif quick_win and row["id"] == quick_win["id"]:
            row["priority_reason"] = "Small high-interest balance: close it, then roll its payment forward."
        elif _decimal(row["apr"]) > 0:
            row["priority_reason"] = "Highest known APR remaining."
        else:
            row["priority_reason"] = "0%/no-interest balance is protected after interest-bearing debt unless a promo deadline requires more."

    first_target = priority[0] if priority else None
    promo_watch = []
    for row in rows:
        if not row["promo_apr_end_date"]:
            continue
        end_date = row["promo_apr_end_date"]
        days_left = (end_date - today).days
        months_left = max(1, int(days_left / 30.44))
        monthly_to_clear = (_decimal(row["balance"]) / Decimal(str(months_left))).quantize(CENT) if months_left else _decimal(row["balance"])
        promo_watch.append({
            "id": row["id"],
            "name": row["name"],
            "owner_name": row["owner_name"],
            "promo_apr_end_date": end_date,
            "days_remaining": max(0, days_left),
            "estimated_monthly_to_clear": monthly_to_clear,
        })

    required_fields = max(1, len(rows) * 3)
    complete_fields = 0
    for row in rows:
        complete_fields += int(row["balance"] is not None)
        complete_fields += int(row["apr"] is not None)
        complete_fields += int(row["minimum_payment"] is not None)
    completeness = round((complete_fields / required_fields) * 100, 0) if rows else 100

    target_payment = None
    if first_target:
        target_payment = _decimal(first_target["minimum_payment"]) + extra_monthly

    return {
        "name": "Plan 1",
        "method": "STABILIZE_QUICK_WIN_AVALANCHE",
        "status": "NEEDS_DATA" if missing_data else "READY",
        "total_debt": total_debt,
        "known_minimum_payments": known_minimums,
        "extra_monthly": extra_monthly,
        "target_monthly_payment": target_payment,
        "data_completeness_percent": completeness,
        "first_target": first_target,
        "priority": priority,
        "missing_data": missing_data,
        "promo_watch": sorted(promo_watch, key=lambda row: row["promo_apr_end_date"]),
        "rules": [
            "Keep every required minimum current before sending extra money.",
            "Do not add new revolving balances while Plan 1 is active unless necessary.",
            "Close the first target, then roll its old minimum plus the extra amount into the next target.",
            "Debts with missing APR or minimum data stay flagged until the ranking is trustworthy.",
            "Protect 0% promotional balances by tracking the expiration date and required payoff pace.",
        ],
    }


def build_finance_briefing(user, extra_monthly=ZERO) -> dict:
    today = timezone.localdate()
    month_start = today.replace(day=1)
    next_30 = today + timedelta(days=30)
    accounts = FinanceAccount.objects.filter(user=user, is_hidden=False)
    liabilities = FinanceLiability.objects.filter(user=user).select_related("account")
    obligations = FinanceObligation.objects.filter(user=user, active=True)
    transactions = FinanceTransaction.objects.filter(user=user, date__gte=month_start, date__lte=today)

    cash = accounts.filter(kind__in=[FinanceAccount.Kind.CHECKING, FinanceAccount.Kind.SAVINGS]).aggregate(v=Sum("current_balance"))["v"] or ZERO
    debt = liabilities.aggregate(v=Sum("outstanding_balance"))["v"] or ZERO
    credit_limit = accounts.filter(kind=FinanceAccount.Kind.CREDIT_CARD).aggregate(v=Sum("credit_limit"))["v"] or ZERO
    credit_balance = accounts.filter(kind=FinanceAccount.Kind.CREDIT_CARD).aggregate(v=Sum("current_balance"))["v"] or ZERO
    utilization = float((credit_balance / credit_limit) * 100) if credit_limit else None
    spending = transactions.filter(amount__gt=0, is_transfer=False).aggregate(v=Sum("amount"))["v"] or ZERO
    income = abs(transactions.filter(amount__lt=0, is_transfer=False).aggregate(v=Sum("amount"))["v"] or ZERO)

    due_bills = obligations.filter(next_due_date__gte=today, next_due_date__lte=next_30)
    due_debt = liabilities.filter(next_payment_date__gte=today, next_payment_date__lte=next_30)
    bills_due = due_bills.aggregate(v=Sum("expected_amount"))["v"] or ZERO
    debt_due = due_debt.aggregate(v=Sum("next_payment_amount"))["v"] or ZERO
    total_due = bills_due + debt_due
    available_after_known = cash - total_due
    safe_to_spend = max(ZERO, available_after_known)
    minimum_payments_total = sum(
        (
            item.minimum_payment
            if item.minimum_payment is not None
            else item.next_payment_amount
            if item.next_payment_amount is not None
            else ZERO
            for item in liabilities
        ),
        ZERO,
    )

    category_spend = {
        row["category_primary"] or "UNCATEGORIZED": row["total"] or ZERO
        for row in transactions.filter(amount__gt=0, is_transfer=False)
        .values("category_primary")
        .annotate(total=Sum("amount"))
    }
    budget_rows = []
    over_budget = []
    for budget in FinanceBudget.objects.filter(user=user, active=True):
        spent = category_spend.get(budget.category, ZERO)
        remaining = budget.monthly_limit - spent
        pct = float((spent / budget.monthly_limit) * 100) if budget.monthly_limit else 0.0
        row = {
            "id": budget.id,
            "name": budget.name,
            "category": budget.category,
            "monthly_limit": budget.monthly_limit,
            "spent": spent,
            "remaining": remaining,
            "percent_used": round(pct, 1),
            "over_budget": remaining < 0,
        }
        budget_rows.append(row)
        if remaining < 0:
            over_budget.append(row)
    budget_headroom = sum((max(ZERO, row["remaining"]) for row in budget_rows), ZERO)

    active_debts = list(liabilities.exclude(outstanding_balance__isnull=True).filter(outstanding_balance__gt=0))
    avalanche_items = sorted(
        active_debts,
        key=lambda item: (
            -(float(_liability_apr(item)) if _liability_apr(item) is not None else -1),
            float(item.outstanding_balance or ZERO),
        ),
    )
    snowball_items = sorted(
        active_debts,
        key=lambda item: (
            float(item.outstanding_balance or ZERO),
            -(float(_liability_apr(item) or ZERO)),
        ),
    )
    avalanche = [_debt_row(item, index) for index, item in enumerate(avalanche_items, 1)]
    snowball = [_debt_row(item, index) for index, item in enumerate(snowball_items, 1)]
    plan_1 = build_debt_plan_1(active_debts, extra_monthly=extra_monthly)

    top_categories = list(
        transactions.filter(amount__gt=0, is_transfer=False)
        .values("category_primary")
        .annotate(total=Sum("amount"))
        .order_by("-total")[:5]
    )
    alerts = []
    recommendations = []
    actions = []

    if total_due > cash:
        alerts.append({
            "severity": "HIGH",
            "code": "OBLIGATIONS_EXCEED_CASH",
            "message": "Known obligations due in the next 30 days exceed available cash.",
        })
        actions.append({
            "priority": 1,
            "code": "PROTECT_CASH",
            "title": "Close the 30-day cash gap",
            "detail": "Review payment timing and pause discretionary spending until known obligations are covered.",
        })
    elif total_due > 0:
        recommendations.append("Reserve known 30-day obligations before treating remaining cash as discretionary.")

    if over_budget:
        names = ", ".join(row["name"] for row in over_budget[:3])
        alerts.append({
            "severity": "MEDIUM",
            "code": "BUDGET_OVERRUN",
            "message": f"Over monthly budget: {names}.",
        })
        actions.append({
            "priority": 2,
            "code": "BUDGET_CORRECTION",
            "title": "Correct over-budget categories",
            "detail": f"Reduce or reallocate spending for {names}.",
        })

    if utilization is not None and utilization >= 30:
        alerts.append({
            "severity": "HIGH" if utilization >= 70 else "MEDIUM",
            "code": "CREDIT_UTILIZATION",
            "message": f"Credit utilization is {round(utilization, 1)}%.",
        })
        recommendations.append("Prioritize revolving-card balances when extra payoff cash is available.")

    cash_flow = income - spending
    if cash_flow < 0:
        alerts.append({
            "severity": "MEDIUM",
            "code": "NEGATIVE_MONTHLY_CASH_FLOW",
            "message": "Recorded spending is ahead of recorded income this month.",
        })

    needs_attention = FinanceConnection.objects.filter(
        user=user,
        status=FinanceConnection.Status.NEEDS_ATTENTION,
    ).count()
    if needs_attention:
        alerts.append({
            "severity": "MEDIUM",
            "code": "CONNECTION_NEEDS_ATTENTION",
            "message": f"{needs_attention} financial connection(s) need attention.",
        })

    if plan_1["first_target"]:
        target = plan_1["first_target"]
        recommendations.append(
            f"Plan 1 target: {target['name']}"
            + (f" at {target['apr']}% APR." if target["apr"] is not None else ".")
        )
        actions.append({
            "priority": 3,
            "code": "EXTRA_DEBT_PAYMENT",
            "title": f"Direct extra debt payment to {target['name']}",
            "detail": "Keep minimums current on all debts; roll every freed payment into the next Plan 1 target.",
        })

    if plan_1["missing_data"]:
        alerts.append({
            "severity": "MEDIUM",
            "code": "DEBT_PLAN_DATA_GAPS",
            "message": f"{len(plan_1['missing_data'])} debt account(s) need APR, minimum, or limit details before the payoff order is fully trustworthy.",
        })

    active_goals = FinanceGoal.objects.filter(user=user, active=True).count()
    if not active_goals:
        recommendations.append("Add a savings or payoff goal so SYNC can measure progress against a target.")

    return {
        "as_of": today,
        "summary": {
            "available_cash": cash,
            "known_30_day_obligations": total_due,
            "available_after_known_obligations": available_after_known,
            "safe_to_spend_now": safe_to_spend,
            "budget_headroom_remaining": budget_headroom,
            "total_debt": debt,
            "known_minimum_payments": minimum_payments_total,
            "credit_utilization_percent": round(utilization, 1) if utilization is not None else None,
            "month_income": income,
            "month_spending": spending,
            "month_cash_flow": cash_flow,
        },
        "budgets": budget_rows,
        "debt_strategy": {
            "recommended_method": "PLAN_1",
            "avalanche": avalanche,
            "snowball": snowball,
        },
        "plan_1": plan_1,
        "alerts": alerts,
        "recommendations": recommendations[:8],
        "actions": sorted(actions, key=lambda item: item["priority"]),
        "top_spending_categories": top_categories,
        "counts": {
            "accounts": accounts.count(),
            "liabilities": liabilities.count(),
            "active_obligations": obligations.count(),
            "active_goals": active_goals,
            "active_budgets": len(budget_rows),
        },
    }
