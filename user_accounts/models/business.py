# user_accounts/models/business.py
from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


def _generate_business_card_code() -> str:
    # Short-ish, URL-safe, stable enough for QR; ~16-20 chars plus prefix
    # Example: "SW-9f2KpL1aQx8zN0Rt"
    return "SW-" + secrets.token_urlsafe(12)


class BusinessCategory(models.Model):
    name = models.CharField(max_length=120, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Business(models.Model):
    name = models.CharField(max_length=180)
    category = models.ForeignKey(BusinessCategory, null=True, blank=True, on_delete=models.SET_NULL)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="owned_businesses", on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    is_active = models.BooleanField(default=True)

    # ---- Business contact/profile ----
    business_email = models.EmailField(blank=True, default="")
    owner_name = models.CharField(max_length=180, blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    logo = models.FileField(upload_to="business_logos/", null=True, blank=True)

    # ---- Business Card (Customer Favorites / QR) ----
    headline = models.CharField(max_length=160, blank=True, default="")
    services_text = models.CharField(max_length=320, blank=True, default="")
    address = models.CharField(max_length=220, blank=True, default="")
    website = models.CharField(max_length=220, blank=True, default="")

    # ✅ NEW: City/State (you requested)
    city = models.CharField(max_length=80, blank=True, default="")
    state = models.CharField(max_length=2, blank=True, default="")  # "AL"

    # ✅ NEW: expected gross monthly (you requested)
    expected_gross_monthly = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # ✅ NEW: yes/no business compliance toggles (you requested)
    is_licensed = models.BooleanField(default=False)
    is_insured = models.BooleanField(default=False)
    is_bonded = models.BooleanField(default=False)
    background_checked = models.BooleanField(default=False)
    emergency_service = models.BooleanField(default=False)

    # This is what customers will paste/scan
    # IMPORTANT: null=True + default=None avoids SQLite unique collisions during migration
    business_card_code = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        default=None,
        help_text="Shareable business card code for customers to add as a favorite (QR/paste).",
    )

    # ---- Marketplace discovery ----
    accepts_marketplace_tickets = models.BooleanField(default=True)
    base_zip = models.CharField(max_length=10, blank=True, default="")
    service_radius_miles = models.PositiveIntegerField(default=25)

    # ✅ This is the bridge for marketplace matching (keep canonical)
    # Businesses should select LEAF service categories (like your Upgrade wizard)
    services_offered = models.ManyToManyField(
        "user_accounts.ServiceCategory",
        blank=True,
        related_name="businesses",
    )

    # ---- Stripe Connect (IMPORTANT) ----
    stripe_connect_account_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Stripe Connect Express account ID (acct_...)",
    )

    # ---- Billing exemption (TRUE FULL EXEMPTION - internal/testing only) ----
    billing_exempt = models.BooleanField(default=False)
    billing_exempt_reason = models.CharField(max_length=255, blank=True, default="")
    billing_exempt_until = models.DateField(null=True, blank=True)

    # ---- Promo Waiver: subscriptions only (SWFF26) ----
    subscriptions_exempt = models.BooleanField(default=False)
    subscriptions_exempt_reason = models.CharField(max_length=255, blank=True, default="")
    subscriptions_exempt_until = models.DateField(null=True, blank=True)

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        # Always ensure code exists for QR/business card sharing
        if not self.business_card_code:
            self.ensure_business_card_code(save=False)
        super().save(*args, **kwargs)

    def is_billing_exempt_now(self) -> bool:
        if not self.billing_exempt:
            return False
        if not self.billing_exempt_until:
            return True
        return self.billing_exempt_until >= timezone.localdate()

    def is_subscriptions_exempt_now(self) -> bool:
        if not self.subscriptions_exempt:
            return False
        if not self.subscriptions_exempt_until:
            return True
        return self.subscriptions_exempt_until >= timezone.localdate()

    def ensure_business_card_code(self, save: bool = True) -> str:
        """
        Ensures this business has a shareable business_card_code.
        Safe to call many times.
        """
        if self.business_card_code:
            return self.business_card_code

        # Try a few times to avoid rare collisions
        for _ in range(10):
            code = _generate_business_card_code()
            if not Business.objects.filter(business_card_code=code).exists():
                self.business_card_code = code
                if save:
                    self.save(update_fields=["business_card_code"])
                return code

        # Extremely unlikely fallback
        code = "SW-" + secrets.token_urlsafe(24)
        self.business_card_code = code
        if save:
            self.save(update_fields=["business_card_code"])
        return code


class BusinessMemberRole(models.TextChoices):
    OWNER = "OWNER", "Owner"
    MANAGER = "MANAGER", "Manager"
    DISPATCH = "DISPATCH", "Dispatch"
    ACCOUNTING = "ACCOUNTING", "Accounting"

    # Preferred technician value going forward
    TECHNICIAN = "TECHNICIAN", "Technician"

    # Legacy technician value (keep to avoid breaking old rows / code)
    TECH = "TECH", "Technician (Legacy)"


class BusinessMember(models.Model):
    # ✅ Back-compat constants referenced throughout the codebase
    ROLE_OWNER = BusinessMemberRole.OWNER
    ROLE_MANAGER = BusinessMemberRole.MANAGER
    ROLE_DISPATCH = BusinessMemberRole.DISPATCH
    ROLE_ACCOUNTING = BusinessMemberRole.ACCOUNTING

    # IMPORTANT: some code references BusinessMember.ROLE_TECH
    # We map it to the preferred value (TECHNICIAN).
    ROLE_TECH = BusinessMemberRole.TECHNICIAN

    ROLE_CHOICES = BusinessMemberRole.choices

    business = models.ForeignKey(Business, related_name="members", on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="business_memberships",
        on_delete=models.CASCADE,
    )

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=BusinessMemberRole.TECHNICIAN)
    is_active = models.BooleanField(default=True)

    # --- permissions ---
    can_manage_team = models.BooleanField(default=False)
    can_manage_settings = models.BooleanField(default=False)

    can_view_financials = models.BooleanField(default=False)
    can_manage_invoices = models.BooleanField(default=False)

    can_create_tickets = models.BooleanField(default=True)
    can_assign_tickets = models.BooleanField(default=False)
    can_close_tickets = models.BooleanField(default=False)

    can_manage_schedule = models.BooleanField(default=False)
    can_manage_categories = models.BooleanField(default=False)
    can_manage_properties = models.BooleanField(default=False)
    can_manage_connections = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("business", "user")]

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.business_id} ({self.role})"

    @property
    def is_owner(self) -> bool:
        return str(self.role) == str(BusinessMemberRole.OWNER)

    def apply_permissions(self, perms: dict[str, bool]) -> None:
        """
        Safe helper used by invite flows:
        member.apply_permissions({"can_assign_tickets": True, ...})
        """
        for k, v in (perms or {}).items():
            if hasattr(self, k):
                setattr(self, k, bool(v))

    def apply_role_defaults(self) -> None:
        """
        Sets default permissions based on role.
        Call this when creating or changing a member role.
        """
        role = str(self.role or "")

        # Owner/Manager: all the things
        if role in {BusinessMemberRole.OWNER, BusinessMemberRole.MANAGER}:
            self.can_manage_team = True
            self.can_manage_settings = True
            self.can_view_financials = True
            self.can_manage_invoices = True
            self.can_assign_tickets = True
            self.can_close_tickets = True
            self.can_manage_schedule = True
            self.can_manage_categories = True
            self.can_manage_properties = True
            self.can_manage_connections = True
            self.can_create_tickets = True
            return

        # Dispatch
        if role == BusinessMemberRole.DISPATCH:
            self.can_assign_tickets = True
            self.can_close_tickets = True
            self.can_manage_schedule = True
            self.can_create_tickets = True
            return

        # Accounting
        if role == BusinessMemberRole.ACCOUNTING:
            self.can_view_financials = True
            self.can_manage_invoices = True
            self.can_create_tickets = True
            return

        # Technician (TECHNICIAN or legacy TECH)
        if role in {BusinessMemberRole.TECHNICIAN, BusinessMemberRole.TECH}:
            self.can_create_tickets = True
            return