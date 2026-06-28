from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from user_accounts.models.business import Business
from user_accounts.models.tickets import Ticket


class TicketETA(models.Model):
    class Status(models.TextChoices):
        ON_TIME = "ON_TIME", "On Time"
        EARLY = "EARLY", "Early"
        DELAYED = "DELAYED", "Delayed"
        ARRIVED = "ARRIVED", "Arrived"
        CANCELLED = "CANCELLED", "Cancelled"

    ticket = models.OneToOneField(
        Ticket,
        on_delete=models.CASCADE,
        related_name="eta",
    )
    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    estimated_arrival = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ON_TIME,
    )
    delay_reason = models.CharField(max_length=255, blank=True, default="")
    customer_message = models.CharField(max_length=500, blank=True, default="")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_etas_updated",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "estimated_arrival"], name="ua_eta_status_time_idx"),
        ]

    def __str__(self):
        return f"ETA for ticket {self.ticket_id}"


class OperationalEvent(models.Model):
    class EventType(models.TextChoices):
        ETA_UPDATED = "ETA_UPDATED", "ETA Updated"
        DELAY_REPORTED = "DELAY_REPORTED", "Delay Reported"
        CREW_EN_ROUTE = "CREW_EN_ROUTE", "Crew En Route"
        CREW_ARRIVED = "CREW_ARRIVED", "Crew Arrived"
        PART_RECEIVED = "PART_RECEIVED", "Part Received"
        JOB_READY = "JOB_READY", "Job Ready"
        JOB_BLOCKED = "JOB_BLOCKED", "Job Blocked"
        STATUS_CHANGED = "STATUS_CHANGED", "Status Changed"
        MESSAGE = "MESSAGE", "Message"
        CUSTOM = "CUSTOM", "Custom"

    class Visibility(models.TextChoices):
        INTERNAL = "INTERNAL", "Internal"
        CUSTOMER = "CUSTOMER", "Customer"
        BOTH = "BOTH", "Both"

    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="operational_events",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="operational_events",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.INTERNAL,
    )
    title = models.CharField(max_length=180)
    message = models.TextField(blank=True, default="")
    data = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operational_events_created",
    )

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["ticket", "occurred_at"], name="ua_event_ticket_time_idx"),
            models.Index(fields=["business", "event_type"], name="ua_event_business_type_idx"),
        ]

    def __str__(self):
        return f"{self.event_type} on ticket {self.ticket_id}"


class OperationalAlert(models.Model):
    class Audience(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Customer"
        BUSINESS = "BUSINESS", "Business"
        USER = "USER", "Specific User"

    class Channel(models.TextChoices):
        IN_APP = "IN_APP", "In App"
        EMAIL = "EMAIL", "Email"
        PUSH = "PUSH", "Push"
        SMS = "SMS", "SMS"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"
        SUPPRESSED = "SUPPRESSED", "Suppressed"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"

    event = models.ForeignKey(
        OperationalEvent,
        on_delete=models.CASCADE,
        related_name="alerts",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="operational_alerts",
        null=True,
        blank=True,
    )
    audience = models.CharField(max_length=16, choices=Audience.choices)
    channel = models.CharField(max_length=16, choices=Channel.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    dedupe_key = models.CharField(max_length=180)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "channel", "dedupe_key"],
                name="ua_alert_dedupe_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["recipient", "status"], name="ua_alert_recipient_idx"),
            models.Index(fields=["event", "channel"], name="ua_alert_event_channel_idx"),
        ]

    def __str__(self):
        return f"{self.channel}:{self.dedupe_key}"
