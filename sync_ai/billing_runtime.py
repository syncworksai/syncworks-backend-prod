from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings as django_settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from user_accounts.models import (
    CommunicationPreference,
    Invoice,
    InvoiceAutomationSettings,
    InvoiceEvent,
    Notification,
)


AUTOMATION_PREFIX = "AUTO_REMINDER_V1"


@dataclass(frozen=True)
class ReminderRule:
    key: str
    label: str


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _balance(invoice: Invoice) -> Decimal:
    return max(Decimal("0.00"), _money(invoice.total) - _money(invoice.amount_paid))


def _rule_for_invoice(invoice: Invoice, automation: InvoiceAutomationSettings, today) -> ReminderRule | None:
    if not invoice.due_date:
        return None

    days_until_due = (invoice.due_date - today).days
    before_days = max(0, int(automation.reminder_before_due_days or 0))

    if before_days > 0 and days_until_due == before_days:
        return ReminderRule(key=f"BEFORE_{before_days}", label=f"due in {before_days} day(s)")

    if days_until_due == 0 and automation.reminder_on_due_date:
        return ReminderRule(key="DUE_DATE", label="due today")

    if days_until_due < 0:
        overdue_days = abs(days_until_due)
        after_days = {max(0, int(value)) for value in (automation.reminder_after_due_days or [])}
        if overdue_days in after_days:
            return ReminderRule(key=f"AFTER_{overdue_days}", label=f"{overdue_days} day(s) overdue")

    return None


def _delivery_reference(invoice: Invoice, rule: ReminderRule, today) -> str:
    return f"{AUTOMATION_PREFIX}:{invoice.id}:{today.isoformat()}:{rule.key}"


def _email_allowed(user) -> bool:
    preference = CommunicationPreference.objects.filter(user=user, business=None).first()
    if preference is None:
        return True
    return bool(preference.email_notifications_enabled)


def _send_customer_email(recipient, invoice: Invoice, business_name: str, balance: Decimal, rule: ReminderRule) -> bool:
    if not getattr(recipient, "email", "") or not _email_allowed(recipient):
        return False
    frontend = (getattr(django_settings, "FRONTEND_URL", "https://syncworksapp.com") or "https://syncworksapp.com").rstrip("/")
    try:
        send_mail(
            subject=f"Payment reminder · Invoice #{invoice.id}",
            message=(
                f"{business_name} has an invoice for ${balance} that is {rule.label}.\n\n"
                f"Review or pay it in SyncWorks: {frontend}/customer/invoices?invoice_id={invoice.id}"
            ),
            from_email=getattr(django_settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[recipient.email],
            fail_silently=False,
        )
        return True
    except Exception:
        return False


def process_invoice_reminders(*, limit: int = 500, today=None) -> dict:
    """Send configured invoice reminders once per rule/date.

    Idempotency is anchored in InvoiceEvent.external_reference so repeated scheduler
    runs cannot create duplicate customer reminders for the same invoice/rule/day.
    """

    today = today or timezone.localdate()
    limit = max(1, min(int(limit or 500), 5000))
    candidates = (
        Invoice.objects.select_related("ticket", "ticket__customer", "ticket__assigned_business")
        .filter(status=Invoice.Status.SENT, due_date__isnull=False, ticket__assigned_business__isnull=False)
        .exclude(ticket__customer__isnull=True)
        .order_by("due_date", "id")[:limit]
    )

    totals = {"checked": 0, "eligible": 0, "sent": 0, "emailed": 0, "deduped": 0, "skipped": 0}

    for candidate in candidates:
        totals["checked"] += 1
        business = candidate.ticket.assigned_business
        automation = InvoiceAutomationSettings.objects.filter(business=business, auto_reminders_enabled=True).first()
        if automation is None:
            totals["skipped"] += 1
            continue

        rule = _rule_for_invoice(candidate, automation, today)
        if rule is None or _balance(candidate) <= 0:
            totals["skipped"] += 1
            continue
        totals["eligible"] += 1

        reference = _delivery_reference(candidate, rule, today)
        with transaction.atomic():
            invoice = (
                Invoice.objects.select_for_update()
                .select_related("ticket", "ticket__customer", "ticket__assigned_business")
                .get(pk=candidate.pk)
            )
            if invoice.status != Invoice.Status.SENT or _balance(invoice) <= 0:
                totals["skipped"] += 1
                continue
            if InvoiceEvent.objects.filter(invoice=invoice, event_type=InvoiceEvent.EventType.REMINDER, external_reference=reference).exists():
                totals["deduped"] += 1
                continue

            recipient = invoice.ticket.customer
            balance = _balance(invoice)
            business_name = invoice.ticket.assigned_business.name
            Notification.objects.create(
                recipient=recipient,
                type=Notification.TYPE_BILLING,
                title=f"Payment reminder · Invoice #{invoice.id}",
                body=f"${balance} remains due to {business_name}; this invoice is {rule.label}.",
                data={
                    "invoice_id": invoice.id,
                    "ticket_id": invoice.ticket_id,
                    "event": "AUTOMATED_PAYMENT_REMINDER",
                    "route": f"/customer/invoices?invoice_id={invoice.id}",
                    "automation_rule": rule.key,
                    "scheduled_for": today.isoformat(),
                },
            )
            emailed = _send_customer_email(recipient, invoice, business_name, balance, rule)
            InvoiceEvent.objects.create(
                invoice=invoice,
                event_type=InvoiceEvent.EventType.REMINDER,
                message=f"Automated payment reminder sent: {rule.label}.",
                external_reference=reference,
                metadata={
                    "automation": AUTOMATION_PREFIX,
                    "rule": rule.key,
                    "scheduled_for": today.isoformat(),
                    "email_delivered": emailed,
                },
            )
            totals["sent"] += 1
            totals["emailed"] += int(emailed)

    return {**totals, "date": today.isoformat()}
