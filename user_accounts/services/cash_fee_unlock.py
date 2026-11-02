"""Release only cash-fee locks after all invoices beyond grace are settled."""
from datetime import date
from django.utils import timezone
from user_accounts.models import CashFeeInvoice
from user_accounts.models.platform_billing import PlatformBillingProfile
from user_accounts.services.cash_fee_policy import should_lock_cash_fees, CASH_LOCK_REASON

def unlock_settled_cash_fees(today: date | None = None) -> int:
    today = today or timezone.localdate()
    released = 0
    profiles = PlatformBillingProfile.objects.filter(is_locked=True, lock_reason=CASH_LOCK_REASON)
    for p in profiles.iterator():
        oldest = CashFeeInvoice.objects.filter(
            business_id=p.business_id,
            status__in=(CashFeeInvoice.Status.OPEN, CashFeeInvoice.Status.OVERDUE),
            due_date__isnull=False,
        ).order_by("due_date").values_list("due_date", flat=True).first()
        if not should_lock_cash_fees(oldest, today):
            p.unlock()
            p.save(update_fields=["is_locked", "locked_at", "lock_reason"])
            released += 1
    return released
