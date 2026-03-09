# backend/user_accounts/models/calendar.py
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.db import models
from django.utils import timezone

try:
    from cryptography.fernet import Fernet
except Exception:
    Fernet = None  # cryptography not installed


User = settings.AUTH_USER_MODEL


def _get_fernet() -> Optional["Fernet"]:
    """
    Production: set env var SYNCWORKS_FERNET_KEY to a urlsafe base64 key.
    Generate once:
      python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    """
    key = os.environ.get("SYNCWORKS_FERNET_KEY", "").strip()
    if not key:
        return None
    if Fernet is None:
        return None
    try:
        return Fernet(key.encode("utf-8"))
    except Exception:
        return None


def encrypt_str(value: str) -> str:
    if not value:
        return ""
    f = _get_fernet()
    if not f:
        # Fail-safe: if encryption isn't configured, we still store.
        # But for true production, set SYNCWORKS_FERNET_KEY.
        return value
    token = f.encrypt(value.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_str(value: str) -> str:
    if not value:
        return ""
    f = _get_fernet()
    if not f:
        return value
    try:
        raw = f.decrypt(value.encode("utf-8"))
        return raw.decode("utf-8")
    except Exception:
        return ""


class CalendarAccount(models.Model):
    PROVIDERS = (
        ("GOOGLE", "Google"),
        ("MICROSOFT", "Microsoft"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="calendar_accounts")
    provider = models.CharField(max_length=20, choices=PROVIDERS)

    # Google: "primary" default
    calendar_id = models.CharField(max_length=255, blank=True, default="primary")

    # OAuth tokens (encrypted at rest if SYNCWORKS_FERNET_KEY set)
    access_token_enc = models.TextField(blank=True, default="")
    refresh_token_enc = models.TextField(blank=True, default="")
    token_expires_at = models.DateTimeField(null=True, blank=True)

    # Provider metadata
    email = models.EmailField(blank=True, default="")
    external_account_id = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("user", "provider", "external_account_id")

    def __str__(self):
        return f"CalendarAccount(user={self.user_id}, provider={self.provider}, active={self.is_active})"

    @property
    def access_token(self) -> str:
        return decrypt_str(self.access_token_enc)

    @access_token.setter
    def access_token(self, value: str):
        self.access_token_enc = encrypt_str(value)

    @property
    def refresh_token(self) -> str:
        return decrypt_str(self.refresh_token_enc)

    @refresh_token.setter
    def refresh_token(self, value: str):
        self.refresh_token_enc = encrypt_str(value)

    def is_expired(self) -> bool:
        if not self.token_expires_at:
            return False
        return timezone.now() >= self.token_expires_at


class TicketCalendarLink(models.Model):
    """
    Stores the external event id per (ticket, user, provider).
    This enables UPDATE on schedule change.
    """
    provider = models.CharField(max_length=20, choices=CalendarAccount.PROVIDERS)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ticket_calendar_links")

    # Ticket is in user_accounts.models.tickets; use string ref to avoid circular import
    ticket = models.ForeignKey("user_accounts.Ticket", on_delete=models.CASCADE, related_name="calendar_links")

    calendar_id = models.CharField(max_length=255, blank=True, default="")
    external_event_id = models.CharField(max_length=255, blank=True, default="")

    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_synced_fingerprint = models.CharField(max_length=64, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        unique_together = ("provider", "user", "ticket")

    def __str__(self):
        return f"TicketCalendarLink(ticket={self.ticket_id}, user={self.user_id}, provider={self.provider})"
