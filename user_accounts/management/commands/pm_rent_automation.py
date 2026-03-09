# backend/user_accounts/management/commands/pm_rent_automation.py
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional, Tuple

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from user_accounts.models import (
    PMBillingSettings,
    PMRentCharge,
    PMRentPayment,
    PMTenant,
    PMUnit,
)


def _money(v) -> Decimal:
    try:
        d = Decimal(str(v))
        return d.quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")


def _today_local() -> date:
    # Your project is America/New_York; still safe if changed.
    return timezone.localdate()


def _month_range(d: date) -> Tuple[date, date]:
    start = d.replace(day=1)
    # next month start
    if start.month == 12:
        nxt = start.replace(year=start.year + 1, month=1)
    else:
        nxt = start.replace(month=start.month + 1)
    end = nxt - timedelta(days=1)
    return start, end


def _send_email(to_email: str, subject: str, body: str, cc_email: str | None = None, from_email: str | None = None):
    if not to_email:
        return False
    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=from_email or getattr(settings, "DEFAULT_FROM_EMAIL", ""),
        to=[to_email],
        cc=[cc_email] if cc_email else None,
    )
    msg.send(fail_silently=True)
    return True


def _resolve_tenant_email(tenant: PMTenant) -> str:
    # Your PMTenant has email field per your output
    return (getattr(tenant, "email", "") or "").strip()


def _charge_exists(biz_id: int, unit_id: int, tenant_id: int, period_start: date, period_end: date) -> bool:
    return PMRentCharge.objects.filter(
        business_id=biz_id,
        unit_id=unit_id,
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
    ).exists()


def _due_date_for_month(settings_obj: PMBillingSettings, period_start: date) -> date:
    # rent_due_day clamps to last day of month
    due_day = int(settings_obj.rent_due_day or 1)
    _, period_end = _month_range(period_start)
    last_day = period_end.day
    due_day = max(1, min(due_day, last_day))
    return period_start.replace(day=due_day)


class Command(BaseCommand):
    help = "PM rent automation: create monthly charges, send reminders/past due emails, assess late fees."

    def add_arguments(self, parser):
        parser.add_argument("--business-id", type=int, default=None, help="Run for a single business_id")
        parser.add_argument("--dry-run", action="store_true", help="Do not write anything, only print actions")
        parser.add_argument("--verbose-actions", action="store_true", help="Print per-record actions")

    def handle(self, *args, **opts):
        business_id = opts.get("business_id")
        dry_run = bool(opts.get("dry_run"))
        verbose_actions = bool(opts.get("verbose_actions"))

        today = _today_local()
        period_start, period_end = _month_range(today)

        qs_settings = PMBillingSettings.objects.all()
        if business_id:
            qs_settings = qs_settings.filter(business_id=business_id)

        total_created = 0
        total_reminders = 0
        total_past_due = 0
        total_late_fees = 0
        total_recomputed = 0

        self.stdout.write(self.style.MIGRATE_HEADING(f"PM rent automation starting (today={today})"))

        for s in qs_settings:
            biz_id = int(s.business_id)

            # ---- 1) Auto-create charges for occupied units with assigned tenant ----
            # We rely on:
            #  - PMTenant.unit_id not null (assigned)
            #  - unit.status == "OCCUPIED" (or anything not VACANT)
            #  - unit.market_rent not null OR tenant has rent_amount OR fallback to last charge
            tenants = PMTenant.objects.select_related("unit", "property").filter(
                business_id=biz_id,
                unit__isnull=False,
            )

            # Best-effort: Only tenants that look active
            # (your status values may vary; safe to not filter too hard)
            # If you have "TENANT" and "APPLICANT", etc., you can tighten later.
            for t in tenants:
                unit: PMUnit | None = getattr(t, "unit", None)
                if not unit:
                    continue

                # Skip vacant units (your unit status enum includes VACANT)
                unit_status = str(getattr(unit, "status", "") or "").upper()
                if unit_status == "VACANT":
                    continue

                # Determine rent amount
                rent = _money(getattr(unit, "market_rent", None))

                # Optional fallback: last charge amount for this unit+tenant
                if rent <= Decimal("0.00"):
                    last_charge = (
                        PMRentCharge.objects.filter(business_id=biz_id, unit_id=unit.id, tenant_id=t.id)
                        .order_by("-period_start")
                        .first()
                    )
                    if last_charge and _money(last_charge.amount) > Decimal("0.00"):
                        rent = _money(last_charge.amount)

                if rent <= Decimal("0.00"):
                    if verbose_actions:
                        self.stdout.write(f"[biz={biz_id}] skip create: unit={unit.id} tenant={t.id} (no rent amount)")
                    continue

                if _charge_exists(biz_id, unit.id, t.id, period_start, period_end):
                    if verbose_actions:
                        self.stdout.write(f"[biz={biz_id}] exists: charge for unit={unit.id} tenant={t.id} {period_start}->{period_end}")
                    continue

                due_date = _due_date_for_month(s, period_start)
                prop_id = getattr(unit, "property_id", None)

                if verbose_actions:
                    self.stdout.write(
                        f"[biz={biz_id}] create charge: prop={prop_id} unit={unit.id} tenant={t.id} "
                        f"rent={rent} due={due_date} period={period_start}->{period_end}"
                    )

                if not dry_run:
                    with transaction.atomic():
                        c = PMRentCharge.objects.create(
                            business_id=biz_id,
                            property_id=prop_id,
                            unit_id=unit.id,
                            tenant_id=t.id,
                            period_start=period_start,
                            period_end=period_end,
                            due_date=due_date,
                            amount=rent,
                            notes=f"Auto rent • {period_start:%b %Y}",
                        )
                        c.recompute()
                        c.save(update_fields=["paid_total", "balance_due", "status", "updated_at"])
                    total_created += 1

            # ---- 2) Reminders + Past Due emails + Late fees ----
            charges = PMRentCharge.objects.filter(business_id=biz_id).select_related("tenant", "unit", "property")

            for c in charges:
                # recompute (keeps status/balance consistent if anything changed)
                if not dry_run:
                    c.recompute()
                    c.save(update_fields=["paid_total", "balance_due", "status", "updated_at"])
                total_recomputed += 1

                # Only act if money still due
                balance = _money(getattr(c, "balance_due", None))
                if balance <= Decimal("0.00"):
                    continue

                due: date = c.due_date
                if not due:
                    continue

                tenant = c.tenant
                if not tenant:
                    continue
                to_email = _resolve_tenant_email(tenant)
                if not to_email:
                    continue

                # --- Reminder BEFORE due ---
                if s.auto_email_enabled and s.email_send_on_due:
                    days_before = int(s.remind_days_before_due or 0)
                    if days_before > 0:
                        remind_on = due - timedelta(days=days_before)
                        if today >= remind_on and today <= due:
                            if c.last_reminder_sent_at is None:
                                subject = "Rent reminder"
                                body = (
                                    f"Hello {getattr(tenant, 'first_name', '')} {getattr(tenant, 'last_name', '')},\n\n"
                                    f"This is a reminder that your rent is due on {due}.\n"
                                    f"Amount due: ${balance}\n\n"
                                    f"If you have any questions, reply to this email.\n"
                                )
                                if verbose_actions:
                                    self.stdout.write(f"[biz={biz_id}] email reminder: charge={c.id} to={to_email}")
                                if not dry_run:
                                    _send_email(to_email, subject, body, from_email=s.resolved_from_email() if hasattr(s, "resolved_from_email") else None)
                                    c.last_reminder_sent_at = timezone.now()
                                    c.save(update_fields=["last_reminder_sent_at", "updated_at"])
                                total_reminders += 1

                # --- Past due email AFTER due ---
                if s.auto_email_enabled and s.email_send_on_past_due:
                    days_after = int(s.remind_days_after_due or 0)
                    past_due_on = due + timedelta(days=max(days_after, 1))
                    if today >= past_due_on:
                        if c.last_past_due_sent_at is None:
                            subject = "Rent past due"
                            body = (
                                f"Hello {getattr(tenant, 'first_name', '')} {getattr(tenant, 'last_name', '')},\n\n"
                                f"Your rent payment is past due.\n"
                                f"Due date: {due}\n"
                                f"Balance due: ${balance}\n\n"
                                f"Please submit payment as soon as possible.\n"
                            )
                            if verbose_actions:
                                self.stdout.write(f"[biz={biz_id}] email past due: charge={c.id} to={to_email}")
                            if not dry_run:
                                _send_email(to_email, subject, body, from_email=s.resolved_from_email() if hasattr(s, "resolved_from_email") else None)
                                c.last_past_due_sent_at = timezone.now()
                                c.save(update_fields=["last_past_due_sent_at", "updated_at"])
                            total_past_due += 1

                # --- Late fee assessment (after grace days) ---
                if s.late_fee_enabled:
                    grace = int(s.grace_days or 0)
                    late_on = due + timedelta(days=grace)
                    if today > late_on and not bool(c.late_fee_assessed):
                        # compute fee using model helper if available
                        if hasattr(s, "calc_late_fee"):
                            fee = _money(s.calc_late_fee(_money(c.amount)))
                        else:
                            # fallback: FLAT or PERCENT
                            fee = Decimal("0.00")
                            tpe = str(getattr(s, "late_fee_type", "FLAT") or "FLAT").upper()
                            if tpe == "PERCENT":
                                pct = _money(getattr(s, "late_fee_percent", "0.00"))
                                fee = (_money(c.amount) * pct).quantize(Decimal("0.01"))
                            else:
                                fee = _money(getattr(s, "late_fee_flat_amount", "0.00"))

                        if fee > Decimal("0.00"):
                            if verbose_actions:
                                self.stdout.write(f"[biz={biz_id}] assess late fee: charge={c.id} fee={fee}")

                            if not dry_run:
                                with transaction.atomic():
                                    c.late_fee_assessed = True
                                    c.late_fee_amount = fee
                                    c.late_fee_assessed_at = timezone.now()
                                    c.recompute()
                                    c.save()

                                # optional email on late fee
                                if s.auto_email_enabled and s.email_send_on_late_fee:
                                    subject = "Late fee assessed"
                                    body = (
                                        f"Hello {getattr(tenant, 'first_name', '')} {getattr(tenant, 'last_name', '')},\n\n"
                                        f"A late fee has been assessed.\n"
                                        f"Due date: {due}\n"
                                        f"Rent: ${_money(c.amount)}\n"
                                        f"Late fee: ${_money(c.late_fee_amount)}\n"
                                        f"New balance due: ${_money(c.balance_due)}\n\n"
                                        f"Please submit payment as soon as possible.\n"
                                    )
                                    _send_email(to_email, subject, body, from_email=s.resolved_from_email() if hasattr(s, "resolved_from_email") else None)
                                    c.last_late_fee_sent_at = timezone.now()
                                    c.save(update_fields=["last_late_fee_sent_at", "updated_at"])

                            total_late_fees += 1

        self.stdout.write(self.style.SUCCESS("PM rent automation completed."))
        self.stdout.write(
            f"created={total_created} reminders={total_reminders} past_due={total_past_due} "
            f"late_fees={total_late_fees} recomputed={total_recomputed} dry_run={dry_run}"
        )
