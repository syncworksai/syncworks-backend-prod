from django.conf import settings
from django.db import models


class CalendarConnection(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="calendar_connections")
    provider = models.CharField(max_length=20)
    external_account_id = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    display_name = models.CharField(max_length=180, blank=True)
    credential_data = models.TextField(blank=True)
    sync_mode = models.CharField(max_length=20, default="TWO_WAY")
    sync_cadence = models.CharField(max_length=20, default="HOURLY")
    enabled = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    next_sync_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("owner", "provider", "external_account_id"), name="pc_unique_calendar_connection")]
