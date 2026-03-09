# backend/user_accounts/models/support_requests.py
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class SupportRequest(models.Model):
    class Kind(models.TextChoices):
        UNLOCK = "UNLOCK", "Unlock Account"
        BILLING = "BILLING", "Billing Question"
        BUG = "BUG", "Bug Report"
        FEATURE = "FEATURE", "Feature Request"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        CLOSED = "CLOSED", "Closed"

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="support_requests",
    )

    role = models.CharField(max_length=32, blank=True, default="")
    business_id = models.IntegerField(null=True, blank=True)

    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.OTHER)
    title = models.CharField(max_length=140, blank=True, default="")
    body = models.TextField(blank=True, default="")

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_requests_handled",
    )
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["kind", "-created_at"]),
            models.Index(fields=["business_id", "-created_at"]),
        ]
        constraints = [
            # ✅ Only ONE OPEN UNLOCK per business+requester at a time (prevents races)
            models.UniqueConstraint(
                fields=["business_id", "requester", "kind", "status"],
                condition=Q(kind="UNLOCK", status="OPEN"),
                name="uniq_open_unlock_per_business_requester",
            )
        ]

    def __str__(self) -> str:
        return f"{self.kind} ({self.status}) #{self.id}"
