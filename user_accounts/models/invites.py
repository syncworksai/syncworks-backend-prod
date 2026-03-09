# backend/user_accounts/models/invites.py
from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from .business import Business, BusinessMemberRole


def generate_code() -> str:
    return secrets.token_urlsafe(16)


def default_expires_at():
    return timezone.now() + timedelta(days=14)


class InviteCode(models.Model):
    """
    Business invites for Employees/Subcontractors.
    """

    business = models.ForeignKey(
        Business,
        related_name="invites",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="created_invites",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    email = models.EmailField(blank=True, null=True)
    code = models.CharField(max_length=64, unique=True, default=generate_code)

    role = models.CharField(
        max_length=20,
        choices=BusinessMemberRole.choices,
        default=BusinessMemberRole.TECHNICIAN,
    )

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
    expires_at = models.DateTimeField(default=default_expires_at)
    used_at = models.DateTimeField(blank=True, null=True)

    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="accepted_invites",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invite {self.code} for {self.business_id}"

    @property
    def is_used(self) -> bool:
        return self.used_at is not None

    @property
    def is_expired(self) -> bool:
        return timezone.now() > self.expires_at