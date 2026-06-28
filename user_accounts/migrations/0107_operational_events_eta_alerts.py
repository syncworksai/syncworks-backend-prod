from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0106_inventory_purchasing"),
    ]

    operations = [
        migrations.CreateModel(
            name="TicketETA",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("window_start", models.DateTimeField(blank=True, null=True)),
                ("window_end", models.DateTimeField(blank=True, null=True)),
                ("estimated_arrival", models.DateTimeField(blank=True, null=True)),
                ("status", models.CharField(choices=[("ON_TIME", "On Time"), ("EARLY", "Early"), ("DELAYED", "Delayed"), ("ARRIVED", "Arrived"), ("CANCELLED", "Cancelled")], default="ON_TIME", max_length=20)),
                ("delay_reason", models.CharField(blank=True, default="", max_length=255)),
                ("customer_message", models.CharField(blank=True, default="", max_length=500)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("ticket", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="eta", to="user_accounts.ticket")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ticket_etas_updated", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="OperationalEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("ETA_UPDATED", "ETA Updated"), ("DELAY_REPORTED", "Delay Reported"), ("CREW_EN_ROUTE", "Crew En Route"), ("CREW_ARRIVED", "Crew Arrived"), ("PART_RECEIVED", "Part Received"), ("JOB_READY", "Job Ready"), ("JOB_BLOCKED", "Job Blocked"), ("STATUS_CHANGED", "Status Changed"), ("MESSAGE", "Message"), ("CUSTOM", "Custom")], max_length=32)),
                ("visibility", models.CharField(choices=[("INTERNAL", "Internal"), ("CUSTOMER", "Customer"), ("BOTH", "Both")], default="INTERNAL", max_length=16)),
                ("title", models.CharField(max_length=180)),
                ("message", models.TextField(blank=True, default="")),
                ("data", models.JSONField(blank=True, default=dict)),
                ("occurred_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="operational_events", to="user_accounts.business")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="operational_events_created", to=settings.AUTH_USER_MODEL)),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="operational_events", to="user_accounts.ticket")),
            ],
            options={"ordering": ["-occurred_at", "-id"]},
        ),
        migrations.CreateModel(
            name="OperationalAlert",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("audience", models.CharField(choices=[("CUSTOMER", "Customer"), ("BUSINESS", "Business"), ("USER", "Specific User")], max_length=16)),
                ("channel", models.CharField(choices=[("IN_APP", "In App"), ("EMAIL", "Email"), ("PUSH", "Push"), ("SMS", "SMS")], max_length=16)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("SENT", "Sent"), ("FAILED", "Failed"), ("SUPPRESSED", "Suppressed"), ("ACKNOWLEDGED", "Acknowledged")], default="PENDING", max_length=20)),
                ("dedupe_key", models.CharField(max_length=180)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("acknowledged_at", models.DateTimeField(blank=True, null=True)),
                ("failure_reason", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="alerts", to="user_accounts.operationalevent")),
                ("recipient", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="operational_alerts", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddIndex(
            model_name="ticketeta",
            index=models.Index(fields=["status", "estimated_arrival"], name="ua_eta_status_time_idx"),
        ),
        migrations.AddIndex(
            model_name="operationalevent",
            index=models.Index(fields=["ticket", "occurred_at"], name="ua_event_ticket_time_idx"),
        ),
        migrations.AddIndex(
            model_name="operationalevent",
            index=models.Index(fields=["business", "event_type"], name="ua_event_business_type_idx"),
        ),
        migrations.AddConstraint(
            model_name="operationalalert",
            constraint=models.UniqueConstraint(fields=("recipient", "channel", "dedupe_key"), name="ua_alert_dedupe_unique"),
        ),
        migrations.AddIndex(
            model_name="operationalalert",
            index=models.Index(fields=["recipient", "status"], name="ua_alert_recipient_idx"),
        ),
        migrations.AddIndex(
            model_name="operationalalert",
            index=models.Index(fields=["event", "channel"], name="ua_alert_event_channel_idx"),
        ),
    ]
