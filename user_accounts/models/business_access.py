# backend/user_accounts/models/business_access.py
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business


class BusinessAccessControl(models.Model):
    """
    Central place to enforce lock/unlock across the platform.
    This avoids modifying the Business model directly and keeps lock state explicit.

    - If is_locked=True, users of that business are blocked from the app
      (except allowlisted endpoints like billing + unlock-request).
    """

    class LockReason(models.TextChoices):
        CARD_EXPIRED = "CARD_EXPIRED", "Card Expired"
        FAILED_PAYMENT = "FAILED_PAYMENT", "Failed Payment"
        MANUAL = "MANUAL", "Manual"
        OTHER = "OTHER", "Other"

    business = models.OneToOneField(Business, on_delete=models.CASCADE, related_name="access_control")

    is_locked = models.BooleanField(default=False)
    lock_reason = models.CharField(max_length=32, choices=LockReason.choices, default=LockReason.OTHER)

    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="business_locks_created",
    )

    last_unlock_requested_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def lock(self, *, reason: str, actor=None) -> None:
        self.is_locked = True
        self.lock_reason = reason
        self.locked_at = timezone.now()
        self.locked_by = actor
        self.save(update_fields=["is_locked", "lock_reason", "locked_at", "locked_by", "updated_at"])

    def unlock(self, *, actor=None) -> None:
        self.is_locked = False
        self.lock_reason = self.LockReason.OTHER
        self.locked_at = None
        self.locked_by = actor
        self.save(update_fields=["is_locked", "lock_reason", "locked_at", "locked_by", "updated_at"])

    def __str__(self) -> str:
        return f"BusinessAccessControl(business_id={self.business_id}, locked={self.is_locked})"
