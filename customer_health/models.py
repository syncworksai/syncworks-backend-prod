from __future__ import annotations

from django.conf import settings
from django.db import models


def default_dict() -> dict:
    return {}


def default_list() -> list:
    return []


class CustomerHealthProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_health_profile",
    )

    profile_json = models.JSONField(default=default_dict, blank=True)
    snapshot_json = models.JSONField(default=default_dict, blank=True)
    workouts_json = models.JSONField(default=default_list, blank=True)
    history_json = models.JSONField(default=default_list, blank=True)
    progress_json = models.JSONField(default=default_list, blank=True)
    devices_json = models.JSONField(default=default_list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Customer Health Profile"
        verbose_name_plural = "Customer Health Profiles"
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        email = getattr(self.user, "email", "") or getattr(self.user, "username", "")
        return f"Customer Health Profile - {email}"

class CustomerHealthFeedback(models.Model):
    STATUS_OPEN = "OPEN"
    STATUS_REVIEWED = "REVIEWED"
    STATUS_CLOSED = "CLOSED"

    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_REVIEWED, "Reviewed"),
        (STATUS_CLOSED, "Closed"),
    ]

    SEVERITY_CHOICES = [
        ("Low", "Low"),
        ("Medium", "Medium"),
        ("High", "High"),
        ("Blocking", "Blocking"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_health_feedback",
    )

    client_feedback_id = models.CharField(
        max_length=128,
        blank=True,
        db_index=True,
    )
    area = models.CharField(max_length=64, blank=True, default="General")
    severity = models.CharField(
        max_length=32,
        choices=SEVERITY_CHOICES,
        default="Medium",
    )
    message = models.TextField()
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN,
        db_index=True,
    )
    source = models.CharField(
        max_length=64,
        blank=True,
        default="health_web_beta",
    )
    page_path = models.CharField(max_length=500, blank=True)
    runtime_json = models.JSONField(default=default_dict, blank=True)
    extra_json = models.JSONField(default=default_dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Customer Health Feedback"
        verbose_name_plural = "Customer Health Feedback"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["severity", "-created_at"]),
        ]

    def __str__(self) -> str:
        email = getattr(self.user, "email", "") or getattr(self.user, "username", "")
        return f"Health Feedback - {self.area} - {email}"
