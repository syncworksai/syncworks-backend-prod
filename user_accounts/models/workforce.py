from __future__ import annotations

from django.db import models

from .business import BusinessMember
from .tickets import Ticket


class WorkforceProfile(models.Model):
    """Operational scheduling profile for one BusinessMember.

    BusinessMember remains the source of truth for identity, role and permissions.
    This profile describes how/when the member can be scheduled.
    """

    member = models.OneToOneField(
        BusinessMember,
        on_delete=models.CASCADE,
        related_name="workforce_profile",
    )
    title = models.CharField(max_length=120, blank=True, default="")
    skills = models.JSONField(default=list, blank=True)
    weekly_availability = models.JSONField(default=dict, blank=True)
    breaks = models.JSONField(default=list, blank=True)
    time_off = models.JSONField(default=list, blank=True)
    default_buffer_minutes = models.PositiveIntegerField(default=0)
    default_job_duration_minutes = models.PositiveIntegerField(default=60)
    route_start_address = models.CharField(max_length=255, blank=True, default="")
    is_schedulable = models.BooleanField(default=True, db_index=True)
    notes = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["member__business_id", "member__user_id"]
        indexes = [
            models.Index(fields=["is_schedulable"], name="ua_workforce_sched_idx"),
        ]

    def __str__(self) -> str:
        return f"Workforce {self.member_id}"


class TicketOperationalProfile(models.Model):
    class Origin(models.TextChoices):
        MARKETPLACE = "MARKETPLACE", "SyncWorks Marketplace"
        BUSINESS_ADDED = "BUSINESS_ADDED", "Business-added customer"
        IMPORTED = "IMPORTED", "Imported work"
        INTERNAL = "INTERNAL", "Internal work"

    class Priority(models.TextChoices):
        EMERGENCY = "EMERGENCY", "Emergency"
        URGENT = "URGENT", "Urgent"
        STANDARD = "STANDARD", "Standard"
        FLEXIBLE = "FLEXIBLE", "Flexible"

    ticket = models.OneToOneField(
        Ticket,
        on_delete=models.CASCADE,
        related_name="operations_profile",
    )
    origin = models.CharField(
        max_length=24,
        choices=Origin.choices,
        default=Origin.BUSINESS_ADDED,
        db_index=True,
    )
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.STANDARD,
        db_index=True,
    )
    estimated_duration_minutes = models.PositiveIntegerField(default=60)
    duration_low_minutes = models.PositiveIntegerField(default=30)
    duration_high_minutes = models.PositiveIntegerField(default=120)
    required_skills = models.JSONField(default=list, blank=True)
    required_staff_count = models.PositiveIntegerField(default=1)
    response_sla_minutes = models.PositiveIntegerField(default=0)
    assignment_sla_minutes = models.PositiveIntegerField(default=0)
    arrival_sla_minutes = models.PositiveIntegerField(default=0)
    completion_sla_minutes = models.PositiveIntegerField(default=0)
    expected_finish_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    customer_visible_note = models.TextField(blank=True, default="")
    internal_note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "ticket_id"]
        indexes = [
            models.Index(fields=["origin", "priority"], name="ua_ticketops_origin_pri_idx"),
            models.Index(fields=["due_at"], name="ua_ticketops_due_idx"),
        ]

    def __str__(self) -> str:
        return f"Ticket ops {self.ticket_id}"
