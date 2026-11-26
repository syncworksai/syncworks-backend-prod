"""Pure onboarding readiness rules; no account connections or financial writes.

Inputs must originate from authorized, verified server records, not user claims
or model output. Persist and recheck evidence before executing any transition.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Milestone:
    key: str
    title: str
    route: str

MILESTONES = (
    Milestone("workspace_verified", "Confirm management workspace", "/pm"),
    Milestone("source_authorized", "Authorize source records or manual import", "/pm"),
    Milestone("property_verified", "Confirm property identity and ownership", "/pm/properties"),
    Milestone("historical_records_reviewed", "Review historical rent and payment records", "/pm/properties"),
    Milestone("opening_balance_approved", "Approve reconciled opening balance", "/pm/properties"),
    Milestone("lease_and_deposit_verified", "Verify lease terms and deposit obligations", "/pm/properties"),
    Milestone("activation_approved", "Approve recurring billing cutover", "/pm/properties"),
    Milestone("tenant_invitation_approved", "Approve tenant portal invitation", "/pm/tenants"),
)

def onboarding_plan(verified, unresolved=()):
    """Return ordered milestones and next action without model inference.

    Unresolved discrepancies are blocking by default; caller supplies only
    outstanding material issues. No tenant invitations are sent here.
    """
    done = set(verified)
    blockers = tuple(dict.fromkeys(str(x) for x in unresolved if x))
    pending = [m for m in MILESTONES if m.key not in done]
    next_step = pending[0] if pending else None
    return {
        "completed": [m.key for m in MILESTONES if m.key in done],
        "next_step": ({"key": next_step.key, "title": next_step.title,
                       "route": next_step.route} if next_step else None),
        "blockers": list(blockers),
        "ready_for_tenant_activation": not pending and not blockers,
        "mode": "PLAN_ONLY",
    }

def escalation_route(kind):
    """Classify external blockers; never authorize a send or legal action."""
    return {
        "missing_statement": "AUTHORIZED_RECORD_PROVIDER",
        "housing_authority": "HOUSING_AUTHORITY_REVIEW",
        "legal": "QUALIFIED_LEGAL_REVIEW",
        "payment_dispute": "ACCOUNTING_REVIEW",
        "connection": "CUSTOMER_CONSENT",
        "emergency": "EMERGENCY_RESPONSE_PROTOCOL",
    }.get(kind, "OWNER_OR_SYDNEY_REVIEW")
