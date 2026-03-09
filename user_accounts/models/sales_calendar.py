# backend/user_accounts/models/sales_calendar.py
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .sales_os import SalesPipeline, SalesPipelineMember, Prospect


User = settings.AUTH_USER_MODEL


class SalesCalendarEvent(models.Model):
    """
    Calendar events for Sales OS.

    MVP:
    - Stored in DB (so we can render Today/Week/Month)
    - Exportable as ICS
    - Add-to links for Google/Outlook based on start/end/subject

    Identity requirement:
    - Organizer email should match agent settings (from_email) if set; otherwise user email.
    """

    pipeline = models.ForeignKey(SalesPipeline, on_delete=models.CASCADE, related_name="calendar_events")
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sales_calendar_events_created",
    )
    assigned_member = models.ForeignKey(
        SalesPipelineMember,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calendar_events_assigned",
    )

    prospect = models.ForeignKey(
        Prospect,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calendar_events",
    )

    title = models.CharField(max_length=180)
    description = models.TextField(blank=True, default="")
    location = models.CharField(max_length=255, blank=True, default="")

    start_at = models.DateTimeField()
    end_at = models.DateTimeField()

    is_all_day = models.BooleanField(default=False)
    is_completed = models.BooleanField(default=False)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["pipeline", "start_at"]),
            models.Index(fields=["pipeline", "end_at"]),
            models.Index(fields=["assigned_member", "start_at"]),
            models.Index(fields=["prospect"]),
        ]
        ordering = ["start_at", "id"]

    def __str__(self) -> str:
        return f"{self.title} ({self.start_at} - {self.end_at})"