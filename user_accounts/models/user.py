from __future__ import annotations

import uuid

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """
    Primary user identity.

    One account can participate across personal, group, family,
    collection, finance, health, business, and other platform modules.
    """

    ROLE_CUSTOMER = "CUSTOMER"
    ROLE_SBO = "SBO"
    ROLE_SUB = "SUB"
    ROLE_EMPLOYEE = "EMPLOYEE"

    ROLE_CHOICES = (
        (ROLE_CUSTOMER, "Customer"),
        (ROLE_SBO, "Small Business Owner"),
        (ROLE_SUB, "Subcontractor"),
        (ROLE_EMPLOYEE, "Employee"),
    )

    REGISTRATION_SOURCE_WEB = "WEB"
    REGISTRATION_SOURCE_INVITATION = "INVITATION"
    REGISTRATION_SOURCE_COLLECTION = "COLLECTION"
    REGISTRATION_SOURCE_BUSINESS = "BUSINESS"
    REGISTRATION_SOURCE_FAMILY = "FAMILY"
    REGISTRATION_SOURCE_INTERNAL = "INTERNAL"

    REGISTRATION_SOURCE_CHOICES = (
        (REGISTRATION_SOURCE_WEB, "Web"),
        (REGISTRATION_SOURCE_INVITATION, "Invitation"),
        (REGISTRATION_SOURCE_COLLECTION, "Collection"),
        (REGISTRATION_SOURCE_BUSINESS, "Business"),
        (REGISTRATION_SOURCE_FAMILY, "Family"),
        (REGISTRATION_SOURCE_INTERNAL, "Internal"),
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_CUSTOMER,
    )

    is_platform_admin = models.BooleanField(
        default=False,
        help_text="Internal platform administration access.",
    )

    email_verified = models.BooleanField(
        default=False,
    )

    email_verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    is_test_account = models.BooleanField(
        default=False,
        help_text="Marks an approved internal testing account.",
    )

    registration_source = models.CharField(
        max_length=32,
        choices=REGISTRATION_SOURCE_CHOICES,
        default=REGISTRATION_SOURCE_WEB,
        blank=True,
    )

    registration_promo_code = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )

    referred_by_affiliate = models.ForeignKey(
        "platform_affiliates.AffiliatePartner",
        related_name="referred_users",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )

    affiliate_referral_code = models.CharField(
        max_length=32,
        blank=True,
        default="",
    )

    affiliate_attributed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    def mark_email_verified(self, *, save: bool = True) -> None:
        self.email_verified = True

        if not self.email_verified_at:
            self.email_verified_at = timezone.now()

        if save:
            self.save(
                update_fields=[
                    "email_verified",
                    "email_verified_at",
                ]
            )

    def __str__(self) -> str:
        return self.username or self.email or f"User#{self.pk}"


class EmailVerificationChallenge(models.Model):
    PURPOSE_REGISTER = "REGISTER"
    PURPOSE_VERIFY_EXISTING = "VERIFY_EXISTING"
    PURPOSE_PASSWORD_RESET = "PASSWORD_RESET"
    PURPOSE_CHANGE_EMAIL = "CHANGE_EMAIL"

    PURPOSE_CHOICES = (
        (PURPOSE_REGISTER, "Register"),
        (PURPOSE_VERIFY_EXISTING, "Verify existing email"),
        (PURPOSE_PASSWORD_RESET, "Password reset"),
        (PURPOSE_CHANGE_EMAIL, "Change email"),
    )

    public_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        db_index=True,
    )

    email = models.EmailField(
        db_index=True,
    )

    purpose = models.CharField(
        max_length=32,
        choices=PURPOSE_CHOICES,
        default=PURPOSE_REGISTER,
        db_index=True,
    )

    code_hash = models.CharField(
        max_length=255,
    )

    expires_at = models.DateTimeField(
        db_index=True,
    )

    verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    consumed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    attempt_count = models.PositiveSmallIntegerField(
        default=0,
    )

    resend_count = models.PositiveSmallIntegerField(
        default=0,
    )

    last_sent_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    requested_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
    )

    user_agent = models.TextField(
        blank=True,
        default="",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ("-created_at",)

        indexes = [
            models.Index(
                fields=["email", "purpose"],
            ),
            models.Index(
                fields=["expires_at"],
            ),
            models.Index(
                fields=["created_at"],
            ),
        ]

    def set_code(self, raw_code: str) -> None:
        self.code_hash = make_password(str(raw_code))

    def check_code(self, raw_code: str) -> bool:
        return check_password(
            str(raw_code),
            self.code_hash,
        )

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_verified(self) -> bool:
        return self.verified_at is not None

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None

    def __str__(self) -> str:
        return f"{self.email} — {self.purpose}"