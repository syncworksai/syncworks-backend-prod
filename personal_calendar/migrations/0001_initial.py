import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="PersonalCalendarEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=180)),
                ("description", models.TextField(blank=True)),
                ("start_at", models.DateTimeField()),
                ("end_at", models.DateTimeField(blank=True, null=True)),
                ("all_day", models.BooleanField(default=False)),
                ("timezone", models.CharField(default="America/Chicago", max_length=64)),
                ("location_name", models.CharField(blank=True, max_length=180)),
                ("address_line1", models.CharField(blank=True, max_length=220)),
                ("address_line2", models.CharField(blank=True, max_length=220)),
                ("city", models.CharField(blank=True, max_length=100)),
                ("state", models.CharField(blank=True, max_length=80)),
                ("postal_code", models.CharField(blank=True, max_length=20)),
                ("country", models.CharField(default="US", max_length=2)),
                ("latitude", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("longitude", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("arrival_buffer_minutes", models.PositiveSmallIntegerField(default=0, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(240)])),
                ("reminder_minutes", models.PositiveIntegerField(default=30, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(10080)])),
                ("recurrence_rule", models.CharField(blank=True, max_length=500)),
                ("source", models.CharField(choices=[("MANUAL", "Manual"), ("SYNC", "SYNC"), ("GOOGLE", "Google Calendar"), ("OUTLOOK", "Outlook"), ("APPLE", "Apple Calendar"), ("TICKET", "Ticket"), ("HEALTH", "Health"), ("SYSTEM", "System")], default="MANUAL", max_length=20)),
                ("external_calendar_id", models.CharField(blank=True, max_length=255)),
                ("external_event_id", models.CharField(blank=True, max_length=255)),
                ("created_by_sync", models.BooleanField(default=False)),
                ("status", models.CharField(choices=[("ACTIVE", "Active"), ("CANCELLED", "Cancelled"), ("ARCHIVED", "Archived")], default="ACTIVE", max_length=20)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="personal_calendar_events", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("start_at", "id")},
        ),
        migrations.CreateModel(
            name="PersonalCalendarEventAudit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("CREATED", "Created"), ("UPDATED", "Updated"), ("CANCELLED", "Cancelled"), ("ARCHIVED", "Archived"), ("DELETED", "Deleted")], max_length=20)),
                ("changes", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="personal_calendar_audit_entries", to=settings.AUTH_USER_MODEL)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="audit_entries", to="personal_calendar.personalcalendarevent")),
            ],
            options={"ordering": ("-created_at", "-id")},
        ),
        migrations.AddIndex(
            model_name="personalcalendarevent",
            index=models.Index(fields=["owner", "status", "start_at"], name="pc_owner_status_start"),
        ),
        migrations.AddIndex(
            model_name="personalcalendarevent",
            index=models.Index(fields=["source", "external_event_id"], name="pc_external_lookup"),
        ),
        migrations.AddConstraint(
            model_name="personalcalendarevent",
            constraint=models.UniqueConstraint(
                condition=~Q(external_event_id=""),
                fields=("owner", "source", "external_calendar_id", "external_event_id"),
                name="pc_unique_external_event",
            ),
        ),
        migrations.AddIndex(
            model_name="personalcalendareventaudit",
            index=models.Index(fields=["event", "created_at"], name="pc_audit_event_created"),
        ),
    ]
