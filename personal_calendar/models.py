from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class PersonalCalendarEvent(models.Model):
    class Source(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        SYNC = "SYNC", "SYNC"
        GOOGLE = "GOOGLE", "Google Calendar"
        OUTLOOK = "OUTLOOK", "Outlook"
        APPLE = "APPLE", "Apple Calendar"
        TICKET = "TICKET", "Ticket"
        HEALTH = "HEALTH", "Health"
        SYSTEM = "SYSTEM", "System"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        CANCELLED = "CANCELLED", "Cancelled"
        ARCHIVED = "ARCHIVED", "Archived"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="personal_calendar_events")
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField(null=True, blank=True)
    all_day = models.BooleanField(default=False)
    timezone = models.CharField(max_length=64, default="America/Chicago")

    location_name = models.CharField(max_length=180, blank=True)
    address_line1 = models.CharField(max_length=220, blank=True)
    address_line2 = models.CharField(max_length=220, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=80, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=2, default="US")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    arrival_buffer_minutes = models.PositiveSmallIntegerField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(240)]
    )
    reminder_minutes = models.PositiveIntegerField(
        default=30, validators=[MinValueValidator(0), MaxValueValidator(10080)]
    )
    recurrence_rule = models.CharField(max_length=500, blank=True)

    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    external_calendar_id = models.CharField(max_length=255, blank=True)
    external_event_id = models.CharField(max_length=255, blank=True)
    created_by_sync = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("start_at", "id")
        indexes = [
            models.Index(fields=("owner", "status", "start_at"), name="pc_owner_status_start"),
            models.Index(fields=("source", "external_event_id"), name="pc_external_lookup"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "source", "external_calendar_id", "external_event_id"),
                condition=~models.Q(external_event_id=""),
                name="pc_unique_external_event",
            )
        ]

    def clean(self):
        super().clean()
        if self.end_at and self.end_at < self.start_at:
            raise ValidationError({"end_at": "End time cannot be before start time."})

    def __str__(self):
        return f"{self.owner_id}: {self.title}"


class PersonalCalendarEventAudit(models.Model):
    class Action(models.TextChoices):
        CREATED = "CREATED", "Created"
        UPDATED = "UPDATED", "Updated"
        CANCELLED = "CANCELLED", "Cancelled"
        ARCHIVED = "ARCHIVED", "Archived"
        DELETED = "DELETED", "Deleted"

    event = models.ForeignKey(PersonalCalendarEvent, on_delete=models.CASCADE, related_name="audit_entries")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="personal_calendar_audit_entries",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    changes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [models.Index(fields=("event", "created_at"), name="pc_audit_event_created")]

    def __str__(self):
        return f"{self.event_id}: {self.action}"
