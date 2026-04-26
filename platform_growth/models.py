from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PlatformCampaign(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        PAUSED = "PAUSED", "Paused"
        COMPLETED = "COMPLETED", "Completed"
        ARCHIVED = "ARCHIVED", "Archived"

    name = models.CharField(max_length=180)
    objective = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    budget_cents = models.PositiveIntegerField(default=0)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="platform_growth_campaigns",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name


class PlatformContent(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SCHEDULED = "SCHEDULED", "Scheduled"
        PUBLISHED = "PUBLISHED", "Published"
        ARCHIVED = "ARCHIVED", "Archived"

    campaign = models.ForeignKey(
        PlatformCampaign,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contents",
    )
    title = models.CharField(max_length=180)
    body = models.TextField(blank=True)
    media_url = models.URLField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="platform_growth_contents",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class PlatformLead(TimeStampedModel):
    class Status(models.TextChoices):
        NEW = "NEW", "New"
        QUALIFIED = "QUALIFIED", "Qualified"
        NURTURING = "NURTURING", "Nurturing"
        WON = "WON", "Won"
        LOST = "LOST", "Lost"

    source = models.CharField(max_length=64, default="META")
    external_id = models.CharField(max_length=120, blank=True)
    full_name = models.CharField(max_length=180, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    score = models.IntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_activity_at = models.DateTimeField(default=timezone.now)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="platform_growth_assigned_leads",
    )

    class Meta:
        ordering = ["-last_activity_at", "-created_at"]
        indexes = [
            models.Index(fields=["source", "external_id"]),
            models.Index(fields=["status", "last_activity_at"]),
        ]

    def __str__(self) -> str:
        return self.full_name or self.email or f"Lead {self.pk}"


class PlatformConversation(TimeStampedModel):
    class Channel(models.TextChoices):
        META = "META", "Meta"
        SMS = "SMS", "SMS"
        EMAIL = "EMAIL", "Email"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        PENDING = "PENDING", "Pending"
        CLOSED = "CLOSED", "Closed"

    lead = models.ForeignKey(PlatformLead, on_delete=models.CASCADE, related_name="conversations")
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.META)
    external_thread_id = models.CharField(max_length=180, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    last_message_at = models.DateTimeField(default=timezone.now)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]
        indexes = [
            models.Index(fields=["channel", "external_thread_id"]),
            models.Index(fields=["status", "last_message_at"]),
        ]


class PlatformMessage(TimeStampedModel):
    class Direction(models.TextChoices):
        INBOUND = "INBOUND", "Inbound"
        OUTBOUND = "OUTBOUND", "Outbound"
        SYSTEM = "SYSTEM", "System"

    conversation = models.ForeignKey(PlatformConversation, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(max_length=20, choices=Direction.choices, default=Direction.INBOUND)
    text = models.TextField(blank=True)
    external_message_id = models.CharField(max_length=180, blank=True)
    sent_at = models.DateTimeField(default=timezone.now)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["sent_at", "created_at"]
        indexes = [
            models.Index(fields=["external_message_id"]),
            models.Index(fields=["sent_at"]),
        ]


class PlatformAutomationFlow(TimeStampedModel):
    name = models.CharField(max_length=180)
    trigger = models.CharField(max_length=120)
    event_type = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="platform_growth_flows",
    )

    class Meta:
        ordering = ["name"]


class PlatformActivationEvent(TimeStampedModel):
    event_type = models.CharField(max_length=120)
    source = models.CharField(max_length=64, default="META")
    external_id = models.CharField(max_length=180, blank=True)
    lead = models.ForeignKey(
        PlatformLead,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activation_events",
    )
    conversation = models.ForeignKey(
        PlatformConversation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activation_events",
    )
    payload = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["source", "event_type"]),
            models.Index(fields=["external_id"]),
        ]
