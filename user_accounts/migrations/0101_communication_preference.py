from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("user_accounts", "0100_business_detailed_services_enabled"),
    ]

    operations = [
        migrations.CreateModel(
            name="CommunicationPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scope", models.CharField(choices=[("PERSONAL", "Personal"), ("BUSINESS", "Business"), ("PROPERTY_MANAGEMENT", "Property Management")], max_length=32)),
                ("internal_inbox_enabled", models.BooleanField(default=True)),
                ("email_notifications_enabled", models.BooleanField(default=True)),
                ("push_notifications_enabled", models.BooleanField(default=True)),
                ("sms_notifications_enabled", models.BooleanField(default=False)),
                ("sms_paid_addon_active", models.BooleanField(default=False)),
                ("sms_consent_confirmed", models.BooleanField(default=False)),
                ("sms_phone_verified", models.BooleanField(default=False)),
                ("automatic_updates_enabled", models.BooleanField(default=True)),
                ("assignment_mode", models.CharField(choices=[("AUTO", "Automatically route"), ("ASSIGNED_ONLY", "Assigned conversations only"), ("SHARED", "Shared team inbox")], default="AUTO", max_length=24)),
                ("owner_oversight_enabled", models.BooleanField(default=True)),
                ("urgent_unread_escalation_enabled", models.BooleanField(default=True)),
                ("email_digest_for_low_priority", models.BooleanField(default=True)),
                ("quiet_hours_enabled", models.BooleanField(default=True)),
                ("quiet_hours_start", models.TimeField(default="21:00")),
                ("quiet_hours_end", models.TimeField(default="07:00")),
                ("emergency_override_enabled", models.BooleanField(default=False)),
                ("timezone", models.CharField(default="America/Chicago", max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="communication_preferences", to="user_accounts.business")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="communication_preferences", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="communicationpreference",
            constraint=models.UniqueConstraint(fields=("user", "business", "scope"), name="uniq_communication_preference_scope"),
        ),
        migrations.AddIndex(
            model_name="communicationpreference",
            index=models.Index(fields=["user", "scope"], name="ua_comm_user_scope_idx"),
        ),
        migrations.AddIndex(
            model_name="communicationpreference",
            index=models.Index(fields=["business", "scope"], name="ua_comm_business_scope_idx"),
        ),
    ]
