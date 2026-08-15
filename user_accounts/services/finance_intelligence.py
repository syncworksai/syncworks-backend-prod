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
    FinanceConnection,
    FinanceGoal,
    FinanceLiability,
    FinanceObligation,
    FinanceTransaction,
)


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
    """Infer recurring outgoing payments without requiring an additional paid AI service."""
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

    created = 0
    updated = 0
    candidates = 0

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
        next_due = latest.date + timedelta(days=cadence_days)
        display_name = latest.merchant_name or latest.description or key.title()
        stream_id = f"SYNC-INFERRED:{key}"

        # A manually tracked item wins over an inferred duplicate with the same name.
        manual_match = FinanceObligation.objects.filter(
            user=user,
            is_manual=True,
            name__iexact=display_name,
            active=True,
        ).exists()
        if manual_match:
            continue

        obligation, was_created = FinanceObligation.objects.update_or_create(
            user=user,
            provider_stream_id=stream_id,
            defaults={
                "name": display_name[:180],
                "merchant": display_name[:180],
                "category": FinanceObligation.Category.SUBSCRIPTIONS,
                "expected_amount": expected_amount,
                "next_due_date": next_due,
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
        if was_created:
            created += 1
        else:
            updated += 1

    return {
        "transactions_scanned": len(transactions),
        "recurring_candidates": candidates,
        "created": created,
        "updated": updated,
    }


def build_finance_briefing(user) -> dict:
    today = timezone.localdate()
    month_start = today.replace(day=1)
    next_30 = today + timedelta(days=30)

    accounts = FinanceAccount.objects.filter(user=user, is_hidden=False)
    liabilities = FinanceLiability.objects.filter(user=user)
    obligations = FinanceObligation.objects.filter(user=user, active=True)
    transactions = FinanceTransaction.objects.filter(user=user, date__gte=month_start, date__lte=today)

    cash = accounts.filter(kind__in=[FinanceAccount.Kind.CHECKING, FinanceAccount.Kind.SAVINGS]).aggregate(v=Sum("current_balance"))["v"] or Decimal("0")
    debt = liabilities.aggregate(v=Sum("outstanding_balance"))["v"] or Decimal("0")
    credit_limit = accounts.filter(kind=FinanceAccount.Kind.CREDIT_CARD).aggregate(v=Sum("credit_limit"))["v"] or Decimal("0")
    credit_balance = accounts.filter(kind=FinanceAccount.Kind.CREDIT_CARD).aggregate(v=Sum("current_balance"))["v"] or Decimal("0")
    utilization = float((credit_balance / credit_limit) * 100) if credit_limit else None

    spending = transactions.filter(amount__gt=0, is_transfer=False).aggregate(v=Sum("amount"))["v"] or Decimal("0")
    income_raw = transactions.filter(amount__lt=0, is_transfer=False).aggregate(v=Sum("amount"))["v"] or Decimal("0")
    income = abs(income_raw)

    due_bills = obligations.filter(next_due_date__gte=today, next_due_date__lte=next_30)
    due_debt = liabilities.filter(next_payment_date__gte=today, next_payment_date__lte=next_30)
    bills_due = due_bills.aggregate(v=Sum("expected_amount"))["v"] or Decimal("0")
    debt_due = due_debt.aggregate(v=Sum("next_payment_amount"))["v"] or Decimal("0")
    total_due = bills_due + debt_due
    available_after_known = cash - total_due

    top_categories = list(
        transactions.filter(amount__gt=0, is_transfer=False)
        .values("category_primary")
        .annotate(total=Sum("amount"))
        .order_by("-total")[:5]
    )

    alerts = []
    recommendations = []

    if total_due > cash:
        alerts.append({
            "severity": "HIGH",
            "code": "OBLIGATIONS_EXCEED_CASH",
            "message": "Known obligations due in the next 30 days exceed available cash.",
        })
        recommendations.append("Review payment timing and discretionary spending before the next known due dates.")
    elif total_due > 0:
        recommendations.append("Keep the known 30-day obligation amount reserved before treating remaining cash as discretionary.")

    if utilization is not None and utilization >= 30:
        alerts.append({
            "severity": "MEDIUM" if utilization < 70 else "HIGH",
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

    needs_attention = FinanceConnection.objects.filter(user=user, status=FinanceConnection.Status.NEEDS_ATTENTION).count()
    if needs_attention:
        alerts.append({
            "severity": "MEDIUM",
            "code": "CONNECTION_NEEDS_ATTENTION",
            "message": f"{needs_attention} financial connection(s) need attention.",
        })

    high_apr = liabilities.filter(apr__gte=Decimal("15")).order_by("-apr").first()
    if high_apr:
        recommendations.append(f"Highest visible APR is {high_apr.apr}% on {high_apr.name}; consider this in the payoff order.")

    active_goals = FinanceGoal.objects.filter(user=user, active=True).count()
    if not active_goals:
        recommendations.append("Add at least one savings or payoff goal so SYNC Assist can measure progress against a target.")

    return {
        "as_of": today,
        "summary": {
            "available_cash": cash,
            "known_30_day_obligations": total_due,
            "available_after_known_obligations": available_after_known,
            "total_debt": debt,
            "credit_utilization_percent": round(utilization, 1) if utilization is not None else None,
            "month_income": income,
            "month_spending": spending,
            "month_cash_flow": cash_flow,
        },
        "alerts": alerts,
        "recommendations": recommendations[:6],
        "top_spending_categories": top_categories,
        "counts": {
            "accounts": accounts.count(),
            "liabilities": liabilities.count(),
            "active_obligations": obligations.count(),
            "active_goals": active_goals,
        },
    }
