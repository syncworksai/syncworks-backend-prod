# platform_growth/models.py
from __future__ import annotations

from datetime import timedelta

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


class GrowthChannelConnection(TimeStampedModel):
    class Provider(models.TextChoices):
        META = "META", "Meta"
        INSTAGRAM = "INSTAGRAM", "Instagram"
        LINKEDIN = "LINKEDIN", "LinkedIn"
        X = "X", "X"
        YOUTUBE = "YOUTUBE", "YouTube"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONNECTED = "CONNECTED", "Connected"
        ERROR = "ERROR", "Error"
        DISCONNECTED = "DISCONNECTED", "Disconnected"

    provider = models.CharField(max_length=32, choices=Provider.choices)
    account_label = models.CharField(max_length=180, blank=True)
    external_account_id = models.CharField(max_length=180, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    scopes = models.JSONField(default=list, blank=True)
    connected_at = models.DateTimeField(null=True, blank=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["provider", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "external_account_id"], name="uniq_growth_provider_external_account"),
        ]


def default_oauth_state_expiry():
    return timezone.now() + timedelta(minutes=15)


class GrowthOAuthState(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        USED = "USED", "Used"
        EXPIRED = "EXPIRED", "Expired"
        CANCELED = "CANCELED", "Canceled"

    provider = models.CharField(max_length=32)
    state = models.CharField(max_length=255, unique=True)
    redirect_uri = models.URLField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField(default=default_oauth_state_expiry)
    used_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["provider", "status"]), models.Index(fields=["expires_at"])]


class GrowthOAuthToken(TimeStampedModel):
    connection = models.ForeignKey(GrowthChannelConnection, on_delete=models.CASCADE, related_name="oauth_tokens")
    provider = models.CharField(max_length=32)
    token_type = models.CharField(max_length=32, blank=True)
    access_token = models.TextField(blank=True)  # TODO: encrypt at rest in a future phase.
    refresh_token = models.TextField(blank=True)  # TODO: encrypt at rest in a future phase.
    expires_at = models.DateTimeField(null=True, blank=True)
    scope = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-created_at"]


class GrowthContentDraft(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        READY = "READY", "Ready"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        ARCHIVED = "ARCHIVED", "Archived"

    title = models.CharField(max_length=180)
    body = models.TextField(blank=True)
    media_urls = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    source = models.CharField(max_length=40, blank=True)
    prompt = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-updated_at", "-created_at"]


class GrowthContentQueueItem(TimeStampedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        SCHEDULED = "SCHEDULED", "Scheduled"
        CANCELED = "CANCELED", "Canceled"
        FAILED = "FAILED", "Failed"
        POSTED = "POSTED", "Posted"

    draft = models.ForeignKey(GrowthContentDraft, on_delete=models.CASCADE, related_name="queue_items")
    channel_connection = models.ForeignKey(GrowthChannelConnection, on_delete=models.CASCADE, related_name="queue_items")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    fail_reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["scheduled_for", "-created_at"]
        indexes = [models.Index(fields=["status", "scheduled_for"])]


class GrowthAutomationRecipe(TimeStampedModel):
    name = models.CharField(max_length=180)
    trigger_type = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    recipe = models.JSONField(default=dict, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["name"]


class GrowthScheduledPostJob(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        READY = "READY", "Ready"
        PAUSED = "PAUSED", "Paused"
        CANCELED = "CANCELED", "Canceled"
        COMPLETED = "COMPLETED", "Completed"

    queue_item = models.ForeignKey(GrowthContentQueueItem, on_delete=models.CASCADE, related_name="scheduled_jobs")
    run_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["run_at", "-created_at"]
        indexes = [models.Index(fields=["status", "run_at"])]


class PlatformAutomationRule(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        PAUSED = "PAUSED", "Paused"
        ARCHIVED = "ARCHIVED", "Archived"

    class TriggerType(models.TextChoices):
        LEAD_CREATED = "lead_created", "Lead Created"
        LEAD_STATUS_CHANGED = "lead_status_changed", "Lead Status Changed"
        TICKET_COMPLETED = "ticket_completed", "Ticket Completed"
        INBOUND_MESSAGE_RECEIVED = "inbound_message_received", "Inbound Message Received"
        CONTENT_DRAFT_CREATED = "content_draft_created", "Content Draft Created"

    class ActionType(models.TextChoices):
        CREATE_FOLLOW_UP_TASK = "create_follow_up_task", "Create Follow-up Task"
        GENERATE_MESSAGE_DRAFT = "generate_message_draft", "Generate Message Draft"
        GENERATE_SOCIAL_POST_DRAFT = "generate_social_post_draft", "Generate Social Post Draft"
        ADD_LEAD_TO_PIPELINE = "add_lead_to_pipeline", "Add Lead To Pipeline"
        LOG_ACTIVATION_EVENT = "log_activation_event", "Log Activation Event"

    name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    trigger_type = models.CharField(max_length=64, choices=TriggerType.choices)
    action_type = models.CharField(max_length=64, choices=ActionType.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    conditions = models.JSONField(default=dict, blank=True)
    action_config = models.JSONField(default=dict, blank=True)
    is_system_template = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["name", "-created_at"]


class PlatformAutomationExecution(models.Model):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        SKIPPED = "SKIPPED", "Skipped"

    rule = models.ForeignKey(PlatformAutomationRule, on_delete=models.CASCADE, related_name="executions")
    trigger_type = models.CharField(max_length=64)
    trigger_payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]