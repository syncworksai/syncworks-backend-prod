# backend/user_accounts/models/platform_billing.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.db import models
from django.utils import timezone


def month_start(d: date) -> date:
    return d.replace(day=1)


def next_month_start(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _last_day_of_month(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


@dataclass
class PlatformPricing:
    """
    Platform billing pricing rules (BUSINESS-scoped).
    """
    included_seats: int = 1
    seat_monthly_cents: int = 1500  # $15/seat example

    # base subscriptions (waived by promo, etc)
    sbo_subscription_cents: int = 1999
    pm_subscription_cents: int = 0

    # platform fee on paid invoices
    platform_fee_bps: int = 100  # 1% = 100 bps


class PlatformBillingProfile(models.Model):
    """
    ✅ BUSINESS-BASED BILLING PROFILE (CORRECT FOR YOUR CURRENT VIEWSETS)
    - This is the "card on file + lock/unlock + monthly invoice" profile
    - It must remain OneToOne(Business) to match your current endpoints that require X-Business-Id
    - DO NOT add a non-nullable user field here (that triggers the makemigrations prompt you saw)
    """
    business = models.OneToOneField(
        "user_accounts.Business",
        on_delete=models.CASCADE,
        related_name="billing_profile",
    )

    # Card-on-file billing
    stripe_customer_id = models.CharField(max_length=128, blank=True, default="")
    stripe_default_payment_method_id = models.CharField(max_length=128, blank=True, default="")
    stripe_setup_complete = models.BooleanField(default=False)

    # ✅ Card snapshot for expiry alerts
    card_brand = models.CharField(max_length=32, blank=True, default="")
    card_last4 = models.CharField(max_length=8, blank=True, default="")
    card_exp_month = models.PositiveSmallIntegerField(null=True, blank=True)
    card_exp_year = models.PositiveSmallIntegerField(null=True, blank=True)
    card_updated_at = models.DateTimeField(null=True, blank=True)

    # ✅ Alert sent flags (prevents spamming)
    warned_30 = models.BooleanField(default=False)
    warned_15 = models.BooleanField(default=False)
    warned_7 = models.BooleanField(default=False)
    warned_1 = models.BooleanField(default=False)
    warned_expired = models.BooleanField(default=False)

    # Locking
    is_locked = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)
    lock_reason = models.CharField(max_length=255, blank=True, default="")

    # Due dates
    next_due_date = models.DateField(null=True, blank=True)
    grace_until = models.DateField(null=True, blank=True)

    # ✅ Subscription fields (kept for future/compat)
    stripe_subscription_id = models.CharField(max_length=128, blank=True, default="")
    subscription_status = models.CharField(max_length=32, blank=True, default="")
    subscription_current_period_end = models.DateTimeField(null=True, blank=True)
    subscription_cancel_at_period_end = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def ensure_due_dates(self):
        today = timezone.localdate()
        if not self.next_due_date:
            self.next_due_date = today + timedelta(days=7)
        if not self.grace_until:
            self.grace_until = (self.next_due_date or today) + timedelta(days=7)

    def lock(self, reason: str):
        self.is_locked = True
        self.locked_at = timezone.now()
        self.lock_reason = reason or "Locked"

    def unlock(self):
        self.is_locked = False
        self.locked_at = None
        self.lock_reason = ""

    # -----------------------
    # Seats (simple default)
    # -----------------------
    def seat_count(self) -> int:
        # If you later bill per seat, wire this to BusinessMember count or a stored quantity.
        return 1

    def extra_seats(self, pricing: PlatformPricing) -> int:
        c = self.seat_count()
        return max(0, int(c) - int(pricing.included_seats))

    # -----------------------
    # ✅ Expiry helpers
    # -----------------------
    def card_expiry_date(self) -> date | None:
        if not self.card_exp_year or not self.card_exp_month:
            return None
        try:
            return _last_day_of_month(int(self.card_exp_year), int(self.card_exp_month))
        except Exception:
            return None

    def days_to_card_expiry(self) -> int | None:
        exp = self.card_expiry_date()
        if not exp:
            return None
        return (exp - timezone.localdate()).days

    def is_card_expired(self) -> bool:
        d = self.days_to_card_expiry()
        return d is not None and d < 0

    def reset_warning_flags(self):
        self.warned_30 = False
        self.warned_15 = False
        self.warned_7 = False
        self.warned_1 = False
        self.warned_expired = False

    def update_card_snapshot(
        self,
        *,
        brand: str = "",
        last4: str = "",
        exp_month: int | None = None,
        exp_year: int | None = None,
    ):
        self.card_brand = (brand or "")[:32]
        self.card_last4 = (last4 or "")[:8]
        self.card_exp_month = exp_month
        self.card_exp_year = exp_year
        self.card_updated_at = timezone.now()
        self.reset_warning_flags()


class MonthlyPlatformBill(models.Model):
    STATUS_DRAFT = "DRAFT"
    STATUS_OPEN = "OPEN"
    STATUS_PAID = "PAID"
    STATUS_FAILED = "FAILED"

    business = models.ForeignKey("user_accounts.Business", on_delete=models.CASCADE)
    profile = models.ForeignKey("user_accounts.PlatformBillingProfile", on_delete=models.CASCADE)

    period_start = models.DateField()
    period_end = models.DateField()

    gross_paid_invoices_cents = models.IntegerField(default=0)
    platform_fee_cents = models.IntegerField(default=0)

    sbo_subscription_cents = models.IntegerField(default=0)
    pm_subscription_cents = models.IntegerField(default=0)
    seats_cents = models.IntegerField(default=0)

    total_due_cents = models.IntegerField(default=0)

    status = models.CharField(max_length=16, default=STATUS_DRAFT)
    due_date = models.DateField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    stripe_invoice_id = models.CharField(max_length=128, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("business", "period_start")
        ordering = ("-period_start",)

    @staticmethod
    def compute_amounts(
        *,
        profile: PlatformBillingProfile,
        pricing: PlatformPricing,
        gross_paid_invoices_cents: int,
        waive_subscriptions: bool = False,
    ):
        """
        Production rule:
        - platform_fee_cents always applies (unless truly billing-exempt in viewset)
        - seats always billable
        - waive_subscriptions only zeros out base subscription line-items (SBO + PM)
        """
        platform_fee_cents = int((int(gross_paid_invoices_cents) * int(pricing.platform_fee_bps)) / 10000)

        extra = profile.extra_seats(pricing)
        seats_cents = int(extra * int(pricing.seat_monthly_cents))

        sbo_cents = 0 if waive_subscriptions else int(pricing.sbo_subscription_cents)
        pm_cents = 0 if waive_subscriptions else int(pricing.pm_subscription_cents)

        total = int(platform_fee_cents + sbo_cents + pm_cents + seats_cents)

        return {
            "gross_paid_invoices_cents": int(gross_paid_invoices_cents),
            "platform_fee_cents": int(platform_fee_cents),
            "sbo_subscription_cents": int(sbo_cents),
            "pm_subscription_cents": int(pm_cents),
            "seats_cents": int(seats_cents),
            "total_due_cents": int(total),
        }