"""Persistent synthetic-only freelance job. No real client content is accepted or saved."""
import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone

class FreelanceSyntheticJob(models.Model):
    class State(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        REVIEW = "REVIEW", "Review needed"
        APPROVED = "APPROVED", "Approved"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="freelance_synthetic_jobs")
    project_id = models.UUIDField(null=True, blank=True)
    state = models.CharField(max_length=12, choices=State.choices, default=State.QUEUED, db_index=True)
    row_count = models.PositiveSmallIntegerField(default=500)
    seed = models.PositiveIntegerField(default=42)
    result = models.JSONField(default=dict, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error_code = models.CharField(max_length=40, blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["state", "created_at"], name="ua_flj_state_created_idx")]
