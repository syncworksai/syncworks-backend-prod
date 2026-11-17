"""Portable three-calendar-month cash invoice grace rule."""
import calendar
from datetime import date

GRACE_MONTHS = 3
CASH_LOCK_REASON = "CASH_FEE_OVERDUE"

def cash_lock_date(due_date: date) -> date:
    month_index = due_date.year * 12 + due_date.month - 1 + GRACE_MONTHS
    year, month_zero_based = divmod(month_index, 12)
    month = month_zero_based + 1
    return date(year, month, min(due_date.day, calendar.monthrange(year, month)[1]))

def should_lock_cash_fees(oldest_unpaid_due: date | None, today: date) -> bool:
    return bool(oldest_unpaid_due and today >= cash_lock_date(oldest_unpaid_due))
