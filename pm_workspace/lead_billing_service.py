"""Server-owned lead add-on catalog and subscription entitlements.

Do not grant access based on a selected UI checkbox or a Checkout redirect.
Only a verified Stripe event can mark a paid workspace ACTIVE.
"""
from decimal import Decimal, ROUND_HALF_UP
from user_accounts.models.user_billing import UserBillingProfile
from .models import PMLeadSubscription

FOUNDER_EMAIL = "jacoblord7@outlook.com"
MAILBOX_PRICE_CENTS = 999
# Feature toggles beyond inbox capture stay unavailable until the corresponding
# worker/test is deployed. They must never be sold before implementation.
CATALOG = {
    "inbox_capture": {"label": "Mailbox lead capture", "price_cents": 999, "available": True, "per_mailbox": True},
    "duplicate_detection": {"label": "Duplicate detection", "price_cents": 0, "available": True, "included": True},
    "quick_messages": {"label": "Quick email and note templates", "price_cents": 0, "available": True, "included": True},
    "ai_extraction": {"label": "AI lead extraction", "price_cents": 999, "available": False},
    "automatic_acknowledgements": {"label": "Automatic acknowledgements", "price_cents": 499, "available": False},
    "follow_up_reminders": {"label": "Smart follow-up reminders", "price_cents": 499, "available": False},
}
ALL_FEATURES = sorted(CATALOG)


def is_founder(user):
    if not user or not user.is_authenticated:
        return False
    if str(getattr(user, "email", "")).strip().lower() != FOUNDER_EMAIL:
        return False
    # A connected, logged-in and verified Personal account owns the email.
    # Beta flags preserve existing founder/tester policy and prevent granting
    # new accounts free access based solely on a typed email address.
    return bool(
        getattr(user, "is_superuser", False) or
        getattr(user, "is_platform_admin", False) or
        UserBillingProfile.objects.filter(
            user=user, beta_subscriptions_waived=True,
        ).exists()
    )


def bundle_discount(mailboxes):
    # Mailbox volume discount; future feature bundle discounts will be added
    # only after their real backend capabilities are released.
    if mailboxes >= 8:
        return 20
    if mailboxes >= 5:
        return 15
    if mailboxes >= 3:
        return 10
    return 0


def price_quote(mailboxes):
    if not isinstance(mailboxes, int) or not 1 <= mailboxes <= 100:
        raise ValueError("Select between 1 and 100 paid mailboxes.")
    subtotal = MAILBOX_PRICE_CENTS * mailboxes
    percent = bundle_discount(mailboxes)
    total = int((Decimal(subtotal) * Decimal(100-percent) / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return {"mailboxes": mailboxes, "subtotal_cents": subtotal, "discount_percent": percent, "monthly_cents": total,
            "features": ["inbox_capture", "duplicate_detection", "quick_messages"]}


def subscription_for(workspace):
    return PMLeadSubscription.objects.filter(workspace=workspace).first()


def has_capture_entitlement(workspace, owner=None):
    owner = owner or workspace.owner
    if is_founder(owner):
        return True
    sub = subscription_for(workspace)
    return bool(sub and sub.is_active() and sub.mailbox_count > 0)


def mailbox_is_entitled(user, workspace, connection_id):
    if not has_capture_entitlement(workspace, user):
        return False
    if is_founder(user):
        return True
    from personal_calendar.connection_store import list_connections
    authorized = []
    for row in list_connections(user):
        if row.get("provider") != "MICROSOFT" or not row.get("enabled", True) or not row.get("mail_enabled"):
            continue
        ids = {str(x) for x in row.get("pm_workspace_ids") or []}
        dest = {str(x).upper() for x in row.get("mail_destinations") or []}
        if str(workspace.id) in ids and "PM" in dest:
            authorized.append(str(row.get("id") or ""))
    sub = subscription_for(workspace)
    return str(connection_id) in authorized[:sub.mailbox_count] if sub else False


def lead_billing_status(workspace, user):
    sub = subscription_for(workspace)
    founder = is_founder(user)
    return {
        "workspace_id": workspace.pk,
        "workspace_name": workspace.name,
        "founder_access": founder,
        "subscription_active": founder or bool(sub and sub.is_active()),
        "subscription_status": "FOUNDER" if founder else sub.status if sub else "NONE",
        "mailbox_limit": None if founder else sub.mailbox_count if sub and sub.is_active() else 0,
        "unlimited_mailboxes": founder,
        "enabled_features": ALL_FEATURES if founder else list(sub.features) if sub and sub.is_active() else [],
        "subscription_id_present": bool(sub and sub.stripe_subscription_id),
        "monthly_cents": 0 if founder else sub.monthly_cents if sub else 0,
        "cancel_at_period_end": bool(sub and sub.cancel_at_period_end),
        "catalog": CATALOG,
        "quotes": [price_quote(n) for n in (1, 2, 3, 5, 8)],
        "checkout_enabled": False,  # overwritten by server environment check in view
    }
