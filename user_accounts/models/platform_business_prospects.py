"""Founder-only acquisition tickets. Separate from a contractor's customer leads."""
from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class PlatformBusinessProspect(models.Model):
    class Status(models.TextChoices):
        NEW = "NEW", "New"
        CONTACTED = "CONTACTED", "Contacted"
        INVITED = "INVITED", "Invitation sent"
        DEMO = "DEMO", "Demo / evaluation"
        REGISTERED = "REGISTERED", "Signed up"
        WON = "WON", "Activated / won"
        LOST = "LOST", "Lost"

    company_name = models.CharField(max_length=200)
    contact_name = models.CharField(max_length=160, blank=True, default="")
    email = models.EmailField(blank=True, default="", db_index=True)
    phone = models.CharField(max_length=40, blank=True, default="")
    industry = models.CharField(max_length=100, blank=True, default="")
    interests = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True, default="")
    next_action = models.CharField(max_length=240, blank=True, default="")
    follow_up_at = models.DateTimeField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    invitation_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    last_invited_at = models.DateTimeField(null=True, blank=True)
    linked_business = models.ForeignKey(
        "user_accounts.Business",
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name="platform_acquisition_prospects",
    )
    signed_up_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name="platform_prospects_created",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["status", "follow_up_at"], name="ua_pbp_status_follow_idx"),
        ]

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        self.company_name = (self.company_name or "").strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Acquisition #{self.id}: {self.company_name}"


class PlatformProspectActivity(models.Model):
    class Kind(models.TextChoices):
        NOTE = "NOTE", "Note"
        CALL = "CALL", "Call"
        EMAIL = "EMAIL", "Email"
        INVITATION = "INVITATION", "Invitation handed to email backend"
        STATUS = "STATUS", "Stage change"
        MEETING = "MEETING", "Meeting / demo"

    prospect = models.ForeignKey(
        PlatformBusinessProspect, on_delete=models.CASCADE, related_name="activities"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, db_index=True)
    subject = models.CharField(max_length=200, blank=True, default="")
    body = models.TextField(blank=True, default="")
    recipient = models.EmailField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name="platform_prospect_activities",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]
