# backend/user_accounts/models/customer_settings.py
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

User = settings.AUTH_USER_MODEL


class CustomerSettings(models.Model):
    class CalendarProvider(models.TextChoices):
        NONE = "NONE", "None"
        GOOGLE = "GOOGLE", "Google"
        OUTLOOK = "OUTLOOK", "Outlook"
        APPLE = "APPLE", "Apple"

    class Prefix(models.TextChoices):
        NONE = "NONE", "—"
        MR = "MR", "Mr."
        MS = "MS", "Ms."
        MRS = "MRS", "Mrs."
        MX = "MX", "Mx."
        DR = "DR", "Dr."

    class PreferredContact(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        SMS = "SMS", "SMS"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="customer_settings")

    # ----------------------------
    # Customer profile (identity)
    # ----------------------------
    prefix = models.CharField(max_length=10, choices=Prefix.choices, default=Prefix.NONE)
    suffix = models.CharField(max_length=20, blank=True, default="")  # Jr, Sr, III, etc.
    phone = models.CharField(max_length=32, blank=True, default="")   # keep flexible (E.164 recommended)

    preferred_contact_method = models.CharField(
        max_length=10,
        choices=PreferredContact.choices,
        default=PreferredContact.EMAIL,
    )

    # Optional profile photo (only show to assigned provider/tech after assignment)
    profile_photo = models.ImageField(upload_to="customers/profile_photos/", null=True, blank=True)

    # ----------------------------
    # Defaults / preferences
    # ----------------------------
    default_zip = models.CharField(max_length=10, blank=True, default="")
    default_address = models.CharField(max_length=255, blank=True, default="")

    notify_email = models.BooleanField(default=True)
    notify_sms = models.BooleanField(default=False)
    notify_push = models.BooleanField(default=True)

    preferred_calendar_provider = models.CharField(
        max_length=20,
        choices=CalendarProvider.choices,
        default=CalendarProvider.NONE,
    )
    calendar_sync_enabled = models.BooleanField(default=False)

    # ----------------------------
    # Payment (card on file) – metadata only
    # NEVER store card numbers. Store Stripe IDs + display fields.
    # ----------------------------
    stripe_customer_id = models.CharField(max_length=128, blank=True, default="")
    stripe_payment_method_id = models.CharField(max_length=128, blank=True, default="")
    stripe_payment_method_brand = models.CharField(max_length=32, blank=True, default="")
    stripe_payment_method_last4 = models.CharField(max_length=4, blank=True, default="")
    stripe_payment_method_exp_month = models.IntegerField(null=True, blank=True)
    stripe_payment_method_exp_year = models.IntegerField(null=True, blank=True)

    # ----------------------------
    # Module entitlements (PAID)
    # ----------------------------
    finance_access = models.BooleanField(default=False)
    finance_until = models.DateField(null=True, blank=True)

    health_access = models.BooleanField(default=False)
    health_until = models.DateField(null=True, blank=True)

    # ----------------------------
    # Questionnaire profiles (JSON)
    # ----------------------------
    finance_profile = models.JSONField(default=dict, blank=True)
    fitness_profile = models.JSONField(default=dict, blank=True)

    # legacy flags
    health_fitness_enabled = models.BooleanField(default=False)
    finance_tools_enabled = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    def __str__(self) -> str:
        return f"CustomerSettings(user_id={self.user_id})"

    @staticmethod
    def _date_is_active(until_date) -> bool:
        if until_date is None:
            return True
        return until_date >= timezone.localdate()

    @staticmethod
    def _is_platform_admin(user) -> bool:
        return bool(getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False))

    def has_finance_access(self) -> bool:
        if self._is_platform_admin(getattr(self, "user", None)):
            return True
        if self.finance_access or self.finance_tools_enabled:
            return self._date_is_active(self.finance_until)
        return False

    def has_health_access(self) -> bool:
        if self._is_platform_admin(getattr(self, "user", None)):
            return True
        if self.health_access or self.health_fitness_enabled:
            return self._date_is_active(self.health_until)
        return False

    def entitlements_payload(self) -> dict:
        return {
            "finance_access": bool(self.has_finance_access()),
            "finance_until": self.finance_until.isoformat() if self.finance_until else None,
            "health_access": bool(self.has_health_access()),
            "health_until": self.health_until.isoformat() if self.health_until else None,
        }

    def payment_payload(self) -> dict:
        return {
            "has_card_on_file": bool(self.stripe_payment_method_id),
            "brand": self.stripe_payment_method_brand or None,
            "last4": self.stripe_payment_method_last4 or None,
            "exp_month": self.stripe_payment_method_exp_month,
            "exp_year": self.stripe_payment_method_exp_year,
        }
