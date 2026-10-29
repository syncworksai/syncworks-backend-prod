"""Safety policy for business cash-fee account lock decisions."""
from datetime import date
from dateutil.relativedelta import relativedelta

GRACE_MONTHS = 3
CASH_LOCK_REASON = "CASH_FEE_OVERDUE"

def should_lock_cash_fees(oldest_unpaid_due: date | None, today: date) -> bool:
    """Grace expires three CALENDAR months after the earliest unpaid due date."""
    return oldest_unpaid_due is not None and today >= (
        oldest_unpaid_due + relativedelta(months=GRACE_MONTHS)
    )
