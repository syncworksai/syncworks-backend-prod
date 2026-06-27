from __future__ import annotations

from django.conf import settings
from django.db import models


class TicketConversationReadState(models.Model):
    class Scope(models.TextChoices):
        PERSONAL = "PERSONAL", "Personal"
        BUSINESS = "BUSINESS", "Business"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ticket_conversation_read_states",
    )
    ticket = models.ForeignKey(
        "user_accounts.Ticket",
        on_delete=models.CASCADE,
        related_name="conversation_read_states",
    )
    scope = models.CharField(max_length=16, choices=Scope.choices)
    last_read_message = models.ForeignKey(
        "user_accounts.TicketMessage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    last_read_at = models.DateTimeField(null=True, blank=True)
    muted = models.BooleanField(default=False)
    pinned = models.BooleanField(default=False)
    needs_attention = models.BooleanField(default=False)
    attention_reason = models.CharField(max_length=255, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "ticket", "scope"],
                name="uniq_ticket_conversation_read_state",
            )
        ]
        indexes = [
            models.Index(fields=["user", "scope", "needs_attention"]),
            models.Index(fields=["ticket", "scope"]),
        ]
