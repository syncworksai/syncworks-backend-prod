from django.conf import settings
from django.db import models


class CalendarConnection(models.Model):
    PROVIDER_CHOICES = (("GOOGLE", "Google"), ("MICROSOFT", "Microsoft / Outlook"), ("APPLE", "Apple / iOS"))
    MODE_CHOICES = (("TWO_WAY", "Two-way"), ("IMPORT_ONLY", "Import only"), ("EXPORT_ONLY", "Export only"))
    CADENCE_CHOICES = (
        ("LIVE", "Live / every minute"),
        ("FIVE_MIN", "Every 5 minutes"),
        ("FIFTEEN_MIN", "Every 15 minutes"),
        ("HOURLY", "Hourly"),
        ("DAILY", "Daily"),
        ("MANUAL", "Manual only"),
    )

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="calendar_connections")
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    external_account_id = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    display_name = models.CharField(max_length=180, blank=True)
    credential_data = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    scopes = models.JSONField(default=list, blank=True)
    sync_mode = models.CharField(max_length=20, choices=MODE_CHOICES, default="TWO_WAY")
    sync_cadence = models.CharField(max_length=20, choices=CADENCE_CHOICES, default="HOURLY")
    enabled = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    next_sync_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("provider", "email", "id")
        constraints = [
            models.UniqueConstraint(fields=("owner", "provider", "external_account_id"), name="pc_unique_calendar_connection")
        ]
        indexes = [
            models.Index(fields=("enabled", "next_sync_at"), name="pc_conn_due_sync"),
            models.Index(fields=("owner", "provider"), name="pc_conn_owner_provider"),
        ]


class CalendarSource(models.Model):
    connection = models.ForeignKey(CalendarConnection, on_delete=models.CASCADE, related_name="calendars")
    external_calendar_id = models.CharField(max_length=500)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    timezone = models.CharField(max_length=80, blank=True)
    color = models.CharField(max_length=40, blank=True)
    is_primary = models.BooleanField(default=False)
    selected = models.BooleanField(default=True)
    write_enabled = models.BooleanField(default=False)
    sync_cursor = models.TextField(blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-is_primary", "name", "id")
        constraints = [
            models.UniqueConstraint(fields=("connection", "external_calendar_id"), name="pc_unique_calendar_source")
        ]


class CalendarEventLink(models.Model):
    event = models.ForeignKey("personal_calendar.PersonalCalendarEvent", on_delete=models.CASCADE, related_name="external_links")
    source = models.ForeignKey(CalendarSource, on_delete=models.CASCADE, related_name="event_links")
    external_event_id = models.CharField(max_length=500)
    external_etag = models.CharField(max_length=255, blank=True)
    remote_updated_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("source", "external_event_id"), name="pc_unique_source_event"),
            models.UniqueConstraint(fields=("event", "source"), name="pc_unique_event_source_link"),
        ]
