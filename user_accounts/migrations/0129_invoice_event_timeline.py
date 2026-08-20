from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0128_ticket_operational_actual_clock"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="InvoiceEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("CREATED", "Created"), ("UPDATED", "Updated"), ("SENT", "Sent"), ("VIEWED", "Viewed"), ("REMINDER", "Reminder"), ("PAYMENT_RECORDED", "Payment recorded"), ("PAYMENT_FAILED", "Payment failed"), ("PAID", "Paid"), ("VOIDED", "Voided"), ("NOTE", "Note")], db_index=True, max_length=32)),
                ("message", models.CharField(blank=True, default="", max_length=500)),
                ("amount", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("payment_source", models.CharField(blank=True, default="", max_length=40)),
                ("external_reference", models.CharField(blank=True, default="", max_length=255)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("occurred_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="invoice_events_created", to=settings.AUTH_USER_MODEL)),
                ("invoice", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="events", to="user_accounts.invoice")),
            ],
            options={"ordering": ["-occurred_at", "-id"]},
        ),
        migrations.AddIndex(
            model_name="invoiceevent",
            index=models.Index(fields=["invoice", "occurred_at"], name="ua_inv_event_time_idx"),
        ),
        migrations.AddIndex(
            model_name="invoiceevent",
            index=models.Index(fields=["event_type", "occurred_at"], name="ua_inv_event_type_idx"),
        ),
    ]
