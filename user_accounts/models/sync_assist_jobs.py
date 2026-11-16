"""Durable, tenant-scoped job record for the Sync Assist private pilot."""
import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class SyncAssistJob(models.Model):
    class State(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        WAITING = "WAITING", "Awaiting owner approval"
        RETRY = "RETRY", "Retry scheduled"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sync_assist_jobs")
    goal_id = models.UUIDField()
    state = models.CharField(max_length=12, choices=State.choices, default=State.QUEUED, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    next_run_at = models.DateTimeField(default=timezone.now, db_index=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True, default="")
    last_receipt_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owner", "goal_id"], name="ua_sa_job_owner_goal_uniq"),
        ]
        indexes = [
            models.Index(fields=["state", "next_run_at"], name="ua_sa_job_state_due_idx"),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"SyncAssistJob {self.goal_id}: {self.state}"
