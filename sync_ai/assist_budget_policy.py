"""Owner-controlled employee sub-limits and pricing targets for Sync Assist pilot.

Account-wide $10 allowance is enforced separately in assist_pilot_budget.
All employee limits here are sub-limits and never additive allowances.
"""
from decimal import Decimal, InvalidOperation
from django.contrib.auth import get_user_model
from django.db import transaction
from user_accounts.models import AuditLog

POLICY_ACTION = "sync_assist.budget.role_limits"
PRICE_TARGETS = {
    "CHIEF_OF_STAFF": "19.99",
    "EXECUTIVE_ASSISTANT": "9.99",
    "RESEARCH_ANALYST": "14.99",
    "SALES_MANAGER": "19.99",
    "MARKETING_MANAGER": "14.99",
    "PROPERTY_MANAGER": "19.99",
}
DEFAULT_LIMIT_CENTS = 1000  # Existing pilot reservations retain compatibility.


def _latest_policy(owner):
    event = AuditLog.objects.filter(actor=owner, action=POLICY_ACTION).order_by("-id").first()
    limits = (event.metadata or {}).get("role_limits_cents", {}) if event else {}
    if not isinstance(limits, dict):
        raise ValueError("Role budget policy is corrupt; paid calls are blocked.")
    return limits


def role_limit_cents(owner, role):
    from .assist_pilot_budget import ALLOWED_ROLES
    if role not in ALLOWED_ROLES:
        raise ValueError("Unsupported role.")
    value = _latest_policy(owner).get(role, DEFAULT_LIMIT_CENTS)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
        raise ValueError("Role budget policy is invalid; paid calls are blocked.")
    return value


def role_limits_snapshot(owner):
    from .assist_pilot_budget import ALLOWED_ROLES
    limits = _latest_policy(owner)
    return {
        role: {
            "limit_usd": f"{role_limit_cents(owner, role) / 100:.2f}",
            "monthly_price_target_usd": PRICE_TARGETS.get(role),
        }
        for role in sorted(ALLOWED_ROLES)
    }


def configure_role_limit(owner, *, role, limit_usd):
    """Persist owner-only role policy under the same owner lock as reservations."""
    from .assist_pilot_budget import ALLOWED_ROLES, RESERVATION_ACTION, _period_bounds, _reservations
    if role not in ALLOWED_ROLES:
        raise ValueError("Unsupported role.")
    try:
        amount = Decimal(str(limit_usd))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid USD limit.") from exc
    if not amount.is_finite() or amount < 0 or amount > 10 or amount.as_tuple().exponent < -2:
        raise ValueError("Role limit must be from $0.00 to $10.00 in whole cents.")
    cents = int(amount * 100)
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=owner.pk)
        start, end = _period_bounds()
        used = sum(
            (metadata or {}).get("reserved_cents", 0)
            for metadata in _reservations(owner, start, end).filter(metadata__role=role).values_list("metadata", flat=True)
        )
        if used > cents:
            raise ValueError("Role limit cannot be below existing monthly reservations.")
        limits = dict(_latest_policy(owner))
        limits[role] = cents
        AuditLog.objects.create(
            actor=owner, action=POLICY_ACTION,
            metadata={"role_limits_cents": limits, "changed_role": role},
        )
    return role_limits_snapshot(owner)
