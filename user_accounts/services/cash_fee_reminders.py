"""Weekly billing reminders. Schedule daily; sends once per 7 days per business."""
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import F
from django.utils import timezone
from user_accounts.models import CashFeeInvoice
from user_accounts.services.cash_fee_policy import should_lock_cash_fees

UNPAID = (CashFeeInvoice.Status.OPEN, CashFeeInvoice.Status.OVERDUE)

def send_cash_fee_reminders(*, today=None, dry_run=False):
    today = today or timezone.localdate()
    now = timezone.now()
    results = {"considered": 0, "sent": 0, "failed": 0, "skipped": 0}
    due = CashFeeInvoice.objects.filter(
        status__in=UNPAID, due_date__lt=today, amount_cents__gt=0,
    ).select_related("business", "business__owner").order_by("business_id", "due_date")

    groups = {}
    for inv in due.iterator():
        groups.setdefault(inv.business_id, []).append(inv)

    for rows in groups.values():
        results["considered"] += 1
        biz = rows[0].business
        if biz.is_billing_exempt_now():
            results["skipped"] += 1
            continue
        # Only one reminder per business per seven days, even with multiple unpaid bills.
        latest = max((row.last_reminder_sent_at for row in rows if row.last_reminder_sent_at), default=None)
        if latest and latest > now - timedelta(days=7):
            results["skipped"] += 1
            continue
        recipient = (getattr(biz.owner, "email", "") or "").strip()
        if not recipient:
            results["skipped"] += 1
            continue
        oldest_due = min(row.due_date for row in rows)
        balance_cents = sum(int(row.amount_cents or 0) for row in rows)
        age_days = (today - oldest_due).days
        lock_now = should_lock_cash_fees(oldest_due, today)
        subject = "SyncWorks: unpaid cash platform fees" + (" — account restricted" if lock_now else "")
        deadline = oldest_due + __import__("dateutil.relativedelta", fromlist=["relativedelta"]).relativedelta(months=3)
        body = (
            f"{biz.name} has ${Decimal(balance_cents) / Decimal(100):,.2f} in unpaid cash-platform-fee invoices.\n"
            f"Oldest payment due: {oldest_due.isoformat()} ({age_days} days ago).\n"
            f"Three-month restriction threshold: {deadline.isoformat()}.\n"
            "If payment remains outstanding at that threshold, business actions may be restricted.\n"
            "Invoices and payment recovery remain accessible during restrictions.\n\n"
            "Review invoices: https://syncworksapp.com/billing/cash-fee-invoices\n"
            "Questions or a payment dispute? Contact SyncWorks support.\n"
            "Do not send bank credentials or card information in reply."
        )
        if dry_run:
            continue
        try:
            if send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient], fail_silently=False) != 1:
                results["failed"] += 1
                continue
        except Exception:
            results["failed"] += 1
            continue
        CashFeeInvoice.objects.filter(pk__in=[row.pk for row in rows]).update(
            last_reminder_sent_at=now, reminder_count=F("reminder_count") + 1
        )
        results["sent"] += 1
    return results
