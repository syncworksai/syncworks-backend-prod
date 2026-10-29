# backend/user_accounts/services/cash_fee_locks.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.utils import timezone

from user_accounts.models import Business, CashFeeInvoice
from user_accounts.services.cash_fee_policy import should_lock_cash_fees, CASH_LOCK_REASON

try:
    from user_accounts.models import PlatformBillingProfile
except Exception:
    PlatformBillingProfile = None  # type: ignore

try:
    from user_accounts.models import BusinessAccessControl
except Exception:
    BusinessAccessControl = None  # type: ignore


@dataclass
class LockRunResult:
    overdue_found: int = 0
    businesses_locked: int = 0
    businesses_skipped_exempt: int = 0
    businesses_unlocked: int = 0
    still_in_grace: int = 0


def _business_is_exempt(b: Business) -> bool:
    try:
        return bool(b.is_billing_exempt_now())
    except Exception:
        if getattr(b, "billing_exempt", False):
            until = getattr(b, "billing_exempt_until", None)
            if until is None:
                return True
            try:
                return until >= timezone.localdate()
            except Exception:
                return True
        return False


def enforce_overdue_cash_fee_locks(*, today: Optional[date] = None) -> LockRunResult:
    """
    Lock only after 3 calendar months past the oldest unpaid cash-fee due date.
    """
    today = today or timezone.localdate()
    res = LockRunResult()

    overdue = (
        CashFeeInvoice.objects.select_related("business")
        .exclude(status=CashFeeInvoice.Status.PAID)
        .exclude(status=CashFeeInvoice.Status.VOID)
        .filter(due_date__lt=today)
    )
    res.overdue_found = overdue.count()

    for inv in overdue.iterator():
        b = inv.business
        if not b:
            continue
        if _business_is_exempt(b):
            res.businesses_skipped_exempt += 1
            continue

        # Mark invoice overdue if model supports it
        if hasattr(CashFeeInvoice, "Status") and getattr(inv, "status", None) != CashFeeInvoice.Status.OVERDUE:
            try:
                inv.status = CashFeeInvoice.Status.OVERDUE
                inv.save(update_fields=["status", "updated_at"] if hasattr(inv, "updated_at") else ["status"])
            except Exception:
                pass

        if not should_lock_cash_fees(inv.due_date, today):
            res.still_in_grace += 1
            continue

        # Lock via PlatformBillingProfile if present, else BusinessAccessControl
        if PlatformBillingProfile is not None:
            prof = PlatformBillingProfile.objects.filter(business=b).first()
            if prof is None:
                prof = PlatformBillingProfile(business=b)

            if getattr(prof, "is_locked", False):
                continue  # Never overwrite a manual or unrelated lock reason.
            if hasattr(prof, "is_locked"):
                prof.is_locked = True
            if hasattr(prof, "lock_reason"):
                prof.lock_reason = "CASH_FEE_OVERDUE"
            if hasattr(prof, "locked_at"):
                prof.locked_at = timezone.now()
            prof.save()
            res.businesses_locked += 1
            continue

        if BusinessAccessControl is not None:
            bac = BusinessAccessControl.objects.filter(business=b).first()
            if bac is None:
                bac = BusinessAccessControl(business=b)

            if hasattr(bac, "is_locked"):
                bac.is_locked = True
            if hasattr(bac, "lock_reason"):
                bac.lock_reason = "CASH_FEE_OVERDUE"
            if hasattr(bac, "locked_at"):
                bac.locked_at = timezone.now()
            bac.save()
            res.businesses_locked += 1

    return res