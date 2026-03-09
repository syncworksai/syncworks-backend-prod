# backend/user_accounts/services/cash_fee_collection.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import stripe
from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models import Business, CashFeeInvoice
from user_accounts.models.platform_billing import PlatformBillingProfile


@dataclass
class CashFeeCollectResult:
    considered: int = 0
    charged: int = 0
    skipped_no_card: int = 0
    skipped_zero: int = 0
    skipped_not_open: int = 0
    failed: int = 0


def _stripe_ready() -> bool:
    return bool(getattr(settings, "STRIPE_SECRET_KEY", ""))


def _get_profile_for_business(business: Business) -> PlatformBillingProfile | None:
    try:
        return PlatformBillingProfile.objects.filter(business=business).first()
    except Exception:
        return None


def charge_cash_fee_invoice(
    *,
    inv: CashFeeInvoice,
    idempotency_key: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Charges a single CashFeeInvoice against the business's PlatformBillingProfile
    using an off-session PaymentIntent.

    Returns: (ok, message)
    """
    if inv.status != CashFeeInvoice.Status.OPEN:
        return False, "Invoice not OPEN."

    inv.mark_overdue_if_needed()

    if inv.amount_cents <= 0:
        inv.last_error = "Amount is 0."
        inv.save(update_fields=["last_error", "status", "updated_at"])
        return False, "Amount is 0."

    if not _stripe_ready():
        return False, "Stripe not configured (STRIPE_SECRET_KEY)."

    stripe.api_key = settings.STRIPE_SECRET_KEY

    biz = inv.business
    prof = _get_profile_for_business(biz)
    if not prof or not prof.stripe_customer_id or not prof.stripe_default_payment_method_id or not prof.stripe_setup_complete:
        inv.attempt_count += 1
        inv.last_attempt_at = timezone.now()
        inv.last_error = "No card on file (setup incomplete)."
        inv.save(update_fields=["attempt_count", "last_attempt_at", "last_error", "updated_at"])
        return False, "No card on file."

    # Stable idempotency key so retries won't double-charge.
    if not idempotency_key:
        ps = str(inv.period_start or "na")
        pe = str(inv.period_end or "na")
        idempotency_key = f"cashfee:{inv.business_id}:{ps}:{pe}:{inv.id}"

    inv.attempt_count += 1
    inv.last_attempt_at = timezone.now()
    inv.last_error = ""
    inv.save(update_fields=["attempt_count", "last_attempt_at", "last_error", "updated_at"])

    try:
        pi = stripe.PaymentIntent.create(
            amount=int(inv.amount_cents),
            currency=inv.currency or "usd",
            customer=prof.stripe_customer_id,
            payment_method=prof.stripe_default_payment_method_id,
            confirm=True,
            off_session=True,
            description=f"SyncWorks cash fee (1% cash GMV) {inv.period_start} -> {inv.period_end}",
            metadata={
                "business_id": str(inv.business_id),
                "cash_fee_invoice_id": str(inv.id),
                "period_start": str(inv.period_start or ""),
                "period_end": str(inv.period_end or ""),
            },
            idempotency_key=idempotency_key,
        )

        inv.stripe_payment_intent_id = pi.get("id") or inv.stripe_payment_intent_id
        latest_charge = pi.get("latest_charge")
        if isinstance(latest_charge, str):
            inv.stripe_charge_id = latest_charge

        if pi.get("status") == "succeeded":
            inv.status = CashFeeInvoice.Status.PAID
            inv.paid_at = timezone.now()
            inv.save(update_fields=["status", "paid_at", "stripe_payment_intent_id", "stripe_charge_id", "updated_at"])
            return True, "Charged successfully."

        inv.last_error = f"PaymentIntent status={pi.get('status')}"
        inv.save(update_fields=["stripe_payment_intent_id", "stripe_charge_id", "last_error", "status", "updated_at"])
        return False, inv.last_error

    except stripe.error.CardError as e:
        inv.last_error = f"Card declined: {str(e)}"
        inv.save(update_fields=["last_error", "status", "updated_at"])
        return False, inv.last_error

    except stripe.error.StripeError as e:
        inv.last_error = f"Stripe error: {str(e)}"
        inv.save(update_fields=["last_error", "status", "updated_at"])
        return False, inv.last_error

    except Exception as e:
        inv.last_error = f"Unexpected error: {str(e)}"
        inv.save(update_fields=["last_error", "status", "updated_at"])
        return False, inv.last_error


def collect_open_cash_fee_invoices(*, due_only: bool = True) -> CashFeeCollectResult:
    """
    Collects OPEN cash fee invoices.
    If due_only=True, only collects invoices with due_date <= today (or no due_date).
    """
    res = CashFeeCollectResult()
    today = timezone.localdate()

    qs = CashFeeInvoice.objects.select_related("business").filter(status=CashFeeInvoice.Status.OPEN)
    if due_only:
        qs = qs.filter(models.Q(due_date__lte=today) | models.Q(due_date__isnull=True))

    for inv in qs.iterator():
        res.considered += 1

        if inv.status != CashFeeInvoice.Status.OPEN:
            res.skipped_not_open += 1
            continue

        if inv.amount_cents <= 0:
            res.skipped_zero += 1
            continue

        ok, msg = charge_cash_fee_invoice(inv=inv)
        if ok:
            res.charged += 1
        else:
            if "No card on file" in msg:
                res.skipped_no_card += 1
            else:
                res.failed += 1

    return res