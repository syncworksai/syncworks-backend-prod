"""Fail-closed, account-wide pilot paid-tool budget (all Sync Assist roles share $10).

Only authorized provider adapters may reserve paid usage BEFORE making any call.
An upper-bound reservation is charged against the allowance immediately,
even if a provider later fails: conservative by design. A provider's actual
invoice and hosting charges cannot be capped by this in-app ledger.
"""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from user_accounts.models import AuditLog

CAP_CENTS = 1000
RESERVATION_ACTION = "sync_assist.budget.paid_tool_reservation"
ALLOWED_ROLES = frozenset({
    "CHIEF_OF_STAFF", "EXECUTIVE_ASSISTANT", "RESEARCH_ANALYST",
    "SALES_MANAGER", "MARKETING_MANAGER", "BUSINESS_MANAGER",
    "FINANCE_MANAGER", "PROPERTY_MANAGER", "CUSTOMER_SERVICE",
    "PERSONAL_TRAINER",
})


class PilotBudgetExceeded(Exception):
    pass


def _period_bounds(now=None):
    now = now or timezone.now()
    start = datetime(now.year, now.month, 1, tzinfo=dt_timezone.utc)
    end = datetime(now.year + (now.month == 12), (now.month % 12) + 1, 1, tzinfo=dt_timezone.utc)
    return start, end


def _reservations(owner, start, end):
    return AuditLog.objects.filter(
        actor=owner,
        action=RESERVATION_ACTION,
        created_at__gte=start,
        created_at__lt=end,
    )


def _cents_from_decimal(amount):
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("A valid decimal USD maximum is required.") from exc
    if not value.is_finite() or value <= 0 or value.as_tuple().exponent < -2:
        raise ValueError("Budget maximum must be positive, finite, and denominated in cents.")
    cents = int(value * 100)
    if cents > CAP_CENTS:
        raise PilotBudgetExceeded("Requested reservation exceeds the entire pilot allowance.")
    return cents


def _used_cents(qs):
    # Bound work and fail closed for malformed ledger entries, rather than
    # accidentally treating missing/invalid costs as zero.
    used = 0
    for metadata in qs.values_list("metadata", flat=True):
        cents = (metadata or {}).get("reserved_cents")
        if isinstance(cents, bool) or not isinstance(cents, int) or cents <= 0:
            raise PilotBudgetExceeded("Budget ledger integrity check failed.")
        used += cents
    return used


def snapshot(owner):
    start, end = _period_bounds()
    reservations = list(_reservations(owner, start, end).values_list("metadata", flat=True))
    spent = _used_cents_from_metadata(reservations)
    roles = {}
    for metadata in reservations:
        role = metadata.get("role")
        roles[role] = roles.get(role, 0) + metadata["reserved_cents"]
    payload = {
        "period": start.strftime("%Y-%m"),
        "limit_usd": "10.00",
        "reserved_usd": f"{spent / 100:.2f}",
        "remaining_usd": f"{max(0, CAP_CENTS - spent) / 100:.2f}",
        "remaining_cents": max(0, CAP_CENTS - spent),
        "status": "exhausted" if spent >= CAP_CENTS else "available",
        "by_role": {role: f"{value / 100:.2f}" for role, value in sorted(roles.items())},
        "provider_charge_coverage": "Sync Assist registered paid-tool reservations only",
        "untracked_costs": ["Render Cron/hosting", "database", "other applications", "provider charges not routed through this guard"],
        "current_internal_worker_model_calls": 0,
        "notice": "A reservation is a conservative upper bound, not a reconciled provider invoice. Unregistered paid tools remain disabled. This is not a Render-wide billing cap.",
    }

    from .assist_budget_policy import role_limits_snapshot
    policies = role_limits_snapshot(owner)
    for role, policy in policies.items():
        reserved = roles.get(role, 0)
        limit = int(Decimal(policy["limit_usd"]) * 100)
        policy["reserved_usd"] = f"{reserved / 100:.2f}"
        policy["remaining_usd"] = f"{max(0, limit - reserved) / 100:.2f}"
    payload["employee_budgets"] = policies
    payload["usage_percent"] = int(spent * 100 / CAP_CENTS)
    payload["alerts"] = [
        {"threshold_percent": threshold, "level": "critical" if threshold == 100 else "warning"}
        for threshold in (75, 90, 100) if spent * 100 >= threshold * CAP_CENTS
    ]
    payload["actual_provider_cost_usd"] = None  # Not reconciled with invoices.
    payload["pricing_status"] = "planning_only"
    return payload


def _used_cents_from_metadata(items):
    used = 0
    for metadata in items:
        cents = (metadata or {}).get("reserved_cents")
        if isinstance(cents, bool) or not isinstance(cents, int) or cents <= 0:
            raise PilotBudgetExceeded("Budget ledger integrity check failed.")
        used += cents
    return used


def reserve_paid_tool(owner, *, role, provider, operation_key, max_usd):
    """Atomically reserve one upper-bounded paid call for this owner.

    Idempotency key must be stable across provider retries. Duplicate attempts
    return the original reservation and do not charge allowance twice.
    Adapters must separately cap max provider tokens/requests; do not execute
    a paid call unless this reservation succeeded.
    """
    if role not in ALLOWED_ROLES:
        raise ValueError("Unsupported role.")
    if not isinstance(provider, str) or not provider.strip() or len(provider) > 100:
        raise ValueError("Provider is required.")
    if not isinstance(operation_key, str) or not 8 <= len(operation_key) <= 160:
        raise ValueError("Stable operation key is required.")
    cents = _cents_from_decimal(max_usd)
    with transaction.atomic():
        # Serializes reservations across different employee roles for one owner.
        get_user_model().objects.select_for_update().get(pk=owner.pk)
        start, end = _period_bounds()
        existing = _reservations(owner, start, end).filter(metadata__operation_key=operation_key).first()
        if existing:
            m = existing.metadata
            if m.get("role") != role or m.get("provider") != provider or m.get("reserved_cents") != cents:
                raise ValueError("Idempotency key reused with different operation parameters.")
            return {"reservation_id": existing.pk, "created": False}
        used = _used_cents(_reservations(owner, start, end))
        from .assist_budget_policy import role_limit_cents
        role_used = _used_cents(_reservations(owner, start, end).filter(metadata__role=role))
        if role_used + cents > role_limit_cents(owner, role):
            raise PilotBudgetExceeded("Employee monthly paid-tool sub-limit exceeded. No paid call authorized.")
        if used + cents > CAP_CENTS:
            raise PilotBudgetExceeded("Shared $10 monthly AI/tool budget exceeded. No paid call authorized.")
        event = AuditLog.objects.create(
            actor=owner,
            action=RESERVATION_ACTION,
            metadata={"role": role, "provider": provider, "operation_key": operation_key, "reserved_cents": cents},
        )
        for threshold in (75, 90, 100):
            if used * 100 < CAP_CENTS * threshold <= (used + cents) * 100:
                AuditLog.objects.create(
                    actor=owner,
                    action="sync_assist.budget.threshold_alert",
                    metadata={"period": start.strftime("%Y-%m"), "threshold_percent": threshold,
                              "reserved_cents": used + cents, "limit_cents": CAP_CENTS},
                )
        return {"reservation_id": event.pk, "created": True}
