from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
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
    transactions = list(FinanceTransaction.objects.filter(user=user, date__gte=cutoff, amount__gt=0, is_transfer=False).order_by("date", "id"))
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
        expected_amount = Decimal(str(median(amounts))).quantize(Decimal("0.01"))
        latest = rows[-1]
        display_name = latest.merchant_name or latest.description or key.title()
        if FinanceObligation.objects.filter(user=user, is_manual=True, name__iexact=display_name, active=True).exists():
            continue
        _, was_created = FinanceObligation.objects.update_or_create(
            user=user,
            provider_stream_id=f"SYNC-INFERRED:{key}",
            defaults={
                "name": display_name[:180], "merchant": display_name[:180],
                "category": FinanceObligation.Category.SUBSCRIPTIONS,
                "expected_amount": expected_amount, "next_due_date": latest.date + timedelta(days=cadence_days),
                "cadence": cadence_name, "recurring": True, "active": True, "is_manual": False,
                "metadata": {"source": "syncworks_recurring_inference", "sample_count": len(rows), "median_interval_days": int(round(float(median(intervals)))) if intervals else None, "latest_transaction_id": latest.id},
            },
        )
        created += int(was_created)
        updated += int(not was_created)
    return {"transactions_scanned": len(transactions), "recurring_candidates": candidates, "created": created, "updated": updated}


def _debt_row(item: FinanceLiability, rank: int) -> dict:
    return {
        "rank": rank,
        "id": item.id,
        "name": item.name,
        "kind": item.kind,
        "balance": item.outstanding_balance or ZERO,
        "apr": item.apr,
        "minimum_payment": item.minimum_payment or ZERO,
    }


def build_finance_briefing(user) -> dict:
    today = timezone.localdate()
    month_start = today.replace(day=1)
    next_30 = today + timedelta(days=30)
    accounts = FinanceAccount.objects.filter(user=user, is_hidden=False)
    liabilities = FinanceLiability.objects.filter(user=user)
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

    category_spend = {row["category_primary"] or "UNCATEGORIZED": row["total"] or ZERO for row in transactions.filter(amount__gt=0, is_transfer=False).values("category_primary").annotate(total=Sum("amount"))}
    budget_rows = []
    over_budget = []
    for budget in FinanceBudget.objects.filter(user=user, active=True):
        spent = category_spend.get(budget.category, ZERO)
        remaining = budget.monthly_limit - spent
        pct = float((spent / budget.monthly_limit) * 100) if budget.monthly_limit else 0.0
        row = {"id": budget.id, "name": budget.name, "category": budget.category, "monthly_limit": budget.monthly_limit, "spent": spent, "remaining": remaining, "percent_used": round(pct, 1), "over_budget": remaining < 0}
        budget_rows.append(row)
        if remaining < 0:
            over_budget.append(row)
    budget_headroom = sum((max(ZERO, row["remaining"]) for row in budget_rows), ZERO)

    active_debts = list(liabilities.exclude(outstanding_balance__isnull=True).filter(outstanding_balance__gt=0))
    avalanche_items = sorted(active_debts, key=lambda item: (-(float(item.apr) if item.apr is not None else -1), float(item.outstanding_balance or ZERO)))
    snowball_items = sorted(active_debts, key=lambda item: (float(item.outstanding_balance or ZERO), -(float(item.apr or ZERO))))
    avalanche = [_debt_row(item, index) for index, item in enumerate(avalanche_items, 1)]
    snowball = [_debt_row(item, index) for index, item in enumerate(snowball_items, 1)]

    top_categories = list(transactions.filter(amount__gt=0, is_transfer=False).values("category_primary").annotate(total=Sum("amount")).order_by("-total")[:5])
    alerts = []
    recommendations = []
    actions = []

    if total_due > cash:
        alerts.append({"severity": "HIGH", "code": "OBLIGATIONS_EXCEED_CASH", "message": "Known obligations due in the next 30 days exceed available cash."})
        actions.append({"priority": 1, "code": "PROTECT_CASH", "title": "Close the 30-day cash gap", "detail": "Review payment timing and pause discretionary spending until known obligations are covered."})
    elif total_due > 0:
        recommendations.append("Reserve known 30-day obligations before treating remaining cash as discretionary.")

    if over_budget:
        names = ", ".join(row["name"] for row in over_budget[:3])
        alerts.append({"severity": "MEDIUM", "code": "BUDGET_OVERRUN", "message": f"Over monthly budget: {names}."})
        actions.append({"priority": 2, "code": "BUDGET_CORRECTION", "title": "Correct over-budget categories", "detail": f"Reduce or reallocate spending for {names}."})

    if utilization is not None and utilization >= 30:
        alerts.append({"severity": "HIGH" if utilization >= 70 else "MEDIUM", "code": "CREDIT_UTILIZATION", "message": f"Credit utilization is {round(utilization, 1)}%."})
        recommendations.append("Prioritize revolving-card balances when extra payoff cash is available.")

    cash_flow = income - spending
    if cash_flow < 0:
        alerts.append({"severity": "MEDIUM", "code": "NEGATIVE_MONTHLY_CASH_FLOW", "message": "Recorded spending is ahead of recorded income this month."})

    needs_attention = FinanceConnection.objects.filter(user=user, status=FinanceConnection.Status.NEEDS_ATTENTION).count()
    if needs_attention:
        alerts.append({"severity": "MEDIUM", "code": "CONNECTION_NEEDS_ATTENTION", "message": f"{needs_attention} financial connection(s) need attention."})

    if avalanche:
        target = avalanche[0]
        recommendations.append(f"Debt avalanche target: {target['name']}" + (f" at {target['apr']}% APR." if target["apr"] is not None else "."))
        actions.append({"priority": 3, "code": "EXTRA_DEBT_PAYMENT", "title": f"Direct extra debt payment to {target['name']}", "detail": "Keep minimums current on all debts; apply available extra payoff cash to the highest-APR balance."})

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
            "credit_utilization_percent": round(utilization, 1) if utilization is not None else None,
            "month_income": income,
            "month_spending": spending,
            "month_cash_flow": cash_flow,
        },
        "budgets": budget_rows,
        "debt_strategy": {"recommended_method": "AVALANCHE", "avalanche": avalanche, "snowball": snowball},
        "alerts": alerts,
        "recommendations": recommendations[:8],
        "actions": sorted(actions, key=lambda item: item["priority"]),
        "top_spending_categories": top_categories,
        "counts": {"accounts": accounts.count(), "liabilities": liabilities.count(), "active_obligations": obligations.count(), "active_goals": active_goals, "active_budgets": len(budget_rows)},
    }
