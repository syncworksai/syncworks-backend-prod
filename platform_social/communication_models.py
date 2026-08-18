from django.conf import settings
from django.db import models

from .models import SocialEvent, SocialGroup


class SocialMessage(models.Model):
    class Kind(models.TextChoices):
        CHAT = "CHAT", "Chat"
        ANNOUNCEMENT = "ANNOUNCEMENT", "Announcement"
        SYSTEM = "SYSTEM", "System"

    group = models.ForeignKey(
        SocialGroup,
        on_delete=models.CASCADE,
        related_name="social_messages",
    )
    event = models.ForeignKey(
        SocialEvent,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="social_messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="social_messages_sent",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.CHAT)
    body = models.TextField(max_length=5000)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [
            models.Index(fields=("group", "event", "created_at"), name="social_msg_group_event"),
            models.Index(fields=("sender", "created_at"), name="social_msg_sender_time"),
        ]

    def __str__(self):
        scope = f"event:{self.event_id}" if self.event_id else "group"
        return f"{self.group_id}/{scope} - {self.sender_id}"
