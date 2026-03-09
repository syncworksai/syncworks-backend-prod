from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business
from user_accounts.models.pm_unit import PMUnit


def _default_expires():
    return timezone.now() + timedelta(days=7)


def _generate_code() -> str:
    # Unique, short-ish, email-safe
    raw = secrets.token_urlsafe(16)
    raw = raw.replace("-", "").replace("_", "")
    return raw[:24].upper()


class PMInvite(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        EXPIRED = "EXPIRED", "Expired"
        REVOKED = "REVOKED", "Revoked"

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="pm_invites")
    unit = models.ForeignKey(PMUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name="invites")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pm_invites_created",
    )

    email = models.EmailField()
    code = models.CharField(max_length=24, unique=True, db_index=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)

    expires_at = models.DateTimeField(default=_default_expires)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["business", "status"]),
            models.Index(fields=["business", "email"]),
        ]

    def save(self, *args, **kwargs):
        if not self.code:
            # ensure code is set even if serializer doesn't pass it
            self.code = _generate_code()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.email} ({self.code}) biz={self.business_id}"
