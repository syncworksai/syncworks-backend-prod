from __future__ import annotations

from django.conf import settings
from django.db import models

User = settings.AUTH_USER_MODEL


class CalendarAccount(models.Model):
    """
    Stores a connected calendar account (OAuth) per user/provider.
    NOTE: Do NOT store raw access tokens in plaintext in production.
    For now this is a model foundation; wire token storage via your preferred secure method:
      - encrypted field
      - external secrets vault
      - token proxy service
    """

    class Provider(models.TextChoices):
        GOOGLE = "GOOGLE", "Google"
        OUTLOOK = "OUTLOOK", "Outlook"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="calendar_accounts")
    provider = models.CharField(max_length=20, choices=Provider.choices)

    # Provider account identifiers
    provider_account_id = models.CharField(max_length=128, blank=True, default="")
    provider_email = models.CharField(max_length=255, blank=True, default="")

    # Token placeholders (wire securely later)
    access_token = models.TextField(blank=True, default="")
    refresh_token = models.TextField(blank=True, default="")
    token_expires_at = models.DateTimeField(null=True, blank=True)

    # Google calendar id / Outlook calendar id
    calendar_id = models.CharField(max_length=128, blank=True, default="")

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        unique_together = ("user", "provider", "provider_account_id")

    def __str__(self) -> str:
        return f"CalendarAccount(user_id={self.user_id}, provider={self.provider})"


class TicketCalendarEvent(models.Model):
    """
    Maps an internal ticket -> external calendar event id for a user.
    This is how you do true updates when the SBO changes schedule.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ticket_calendar_events")
    ticket_id = models.IntegerField()  # avoid circular imports; you can swap to FK later if you want

    provider = models.CharField(max_length=20, blank=True, default="")
    calendar_id = models.CharField(max_length=128, blank=True, default="")
    external_event_id = models.CharField(max_length=255, blank=True, default="")

    last_synced_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        unique_together = ("user", "ticket_id", "provider", "external_event_id")

    def __str__(self) -> str:
        return f"TicketCalendarEvent(user_id={self.user_id}, ticket_id={self.ticket_id})"
