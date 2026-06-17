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