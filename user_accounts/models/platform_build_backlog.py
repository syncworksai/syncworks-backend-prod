from __future__ import annotations

from django.conf import settings
from django.db import models


class PlatformBuildBacklogItem(models.Model):
    class Status(models.TextChoices):
        IDEA = "IDEA", "Idea"
        BUILD_LATER = "BUILD_LATER", "Build later"
        NEXT = "NEXT", "Next"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        TESTING = "TESTING", "Testing"
        DONE = "DONE", "Done"

    class Priority(models.TextChoices):
        URGENT = "URGENT", "Urgent"
        HIGH = "HIGH", "High"
        MEDIUM = "MEDIUM", "Medium"
        LOW = "LOW", "Low"

    title = models.CharField(max_length=220)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.BUILD_LATER, db_index=True)
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.MEDIUM, db_index=True)
    module = models.CharField(max_length=120, blank=True, default="General", db_index=True)
    source = models.CharField(max_length=120, blank=True, default="God Mode")
    notes = models.TextField(blank=True, default="")
    github_issue_number = models.PositiveIntegerField(null=True, blank=True, unique=True)
    github_url = models.URLField(blank=True, default="")
    github_sync_error = models.CharField(max_length=300, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="platform_backlog_items_created")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="platform_backlog_items_updated")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["status", "priority"], name="ua_backlog_status_priority_idx"),
            models.Index(fields=["module", "updated_at"], name="ua_backlog_module_updated_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.status}: {self.title}"
