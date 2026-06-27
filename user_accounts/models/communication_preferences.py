from __future__ import annotations

from django.conf import settings
from django.db import models


class CommunicationPreference(models.Model):
    class Scope(models.TextChoices):
        PERSONAL = "PERSONAL", "Personal"
        BUSINESS = "BUSINESS", "Business"
        PROPERTY_MANAGEMENT = "PROPERTY_MANAGEMENT", "Property Management"

    class AssignmentMode(models.TextChoices):
        AUTO = "AUTO", "Automatically route"
        ASSIGNED_ONLY = "ASSIGNED_ONLY", "Assigned conversations only"
        SHARED = "SHARED", "Shared team inbox"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="communication_preferences",
    )
    business = models.ForeignKey(
        "user_accounts.Business",
        on_delete=models.CASCADE,
        related_name="communication_preferences",
        null=True,
        blank=True,
    )
    scope = models.CharField(max_length=32, choices=Scope.choices)

    internal_inbox_enabled = models.BooleanField(default=True)
    email_notifications_enabled = models.BooleanField(default=True)
    push_notifications_enabled = models.BooleanField(default=True)

    sms_notifications_enabled = models.BooleanField(default=False)
    sms_paid_addon_active = models.BooleanField(default=False)
    sms_consent_confirmed = models.BooleanField(default=False)
    sms_phone_verified = models.BooleanField(default=False)

    automatic_updates_enabled = models.BooleanField(default=True)
    assignment_mode = models.CharField(
        max_length=24,
        choices=AssignmentMode.choices,
        default=AssignmentMode.AUTO,
    )
    owner_oversight_enabled = models.BooleanField(default=True)
    urgent_unread_escalation_enabled = models.BooleanField(default=True)
    email_digest_for_low_priority = models.BooleanField(default=True)

    quiet_hours_enabled = models.BooleanField(default=True)
    quiet_hours_start = models.TimeField(default="21:00")
    quiet_hours_end = models.TimeField(default="07:00")
    emergency_override_enabled = models.BooleanField(default=False)
    timezone = models.CharField(max_length=64, default="America/Chicago")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "business", "scope"],
                name="uniq_communication_preference_scope",
            )
        ]
        indexes = [
            models.Index(fields=["user", "scope"]),
            models.Index(fields=["business", "scope"]),
        ]

    @property
    def sms_ready(self) -> bool:
        return bool(
            self.sms_paid_addon_active
            and self.sms_consent_confirmed
            and self.sms_phone_verified
        )
