from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("user_accounts", "0129_invoice_event_timeline")]

    operations = [
        migrations.CreateModel(
            name="InvoiceAutomationSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("auto_send_invoices", models.BooleanField(default=False)),
                ("due_terms", models.CharField(choices=[("DUE_ON_RECEIPT", "Due on receipt"), ("NET_7", "Net 7"), ("NET_15", "Net 15"), ("NET_30", "Net 30"), ("NET_45", "Net 45"), ("CUSTOM", "Custom")], default="NET_15", max_length=24)),
                ("custom_due_days", models.PositiveIntegerField(default=14)),
                ("auto_reminders_enabled", models.BooleanField(default=False)),
                ("reminder_before_due_days", models.PositiveIntegerField(default=3)),
                ("reminder_on_due_date", models.BooleanField(default=True)),
                ("reminder_after_due_days", models.JSONField(blank=True, default=list)),
                ("pause_new_non_emergency_work_when_overdue", models.BooleanField(default=False)),
                ("overdue_pause_threshold_days", models.PositiveIntegerField(default=30)),
                ("overdue_pause_threshold_cents", models.PositiveBigIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="invoice_automation_settings", to="user_accounts.business")),
            ],
            options={"ordering": ["business_id"]},
        ),
    ]
