from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("user_accounts", "0131_production_readiness_state")]

    operations = [
        migrations.CreateModel(
            name="StripeWebhookEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("stripe_event_id", models.CharField(db_index=True, max_length=255, unique=True)),
                ("event_type", models.CharField(blank=True, db_index=True, default="", max_length=255)),
                ("endpoint", models.CharField(blank=True, db_index=True, default="", max_length=120)),
                ("object_id", models.CharField(blank=True, db_index=True, default="", max_length=255)),
                ("livemode", models.BooleanField(default=False)),
                ("api_version", models.CharField(blank=True, default="", max_length=64)),
                ("status", models.CharField(choices=[("RECEIVED", "Received"), ("PROCESSED", "Processed"), ("IGNORED", "Ignored"), ("FAILED", "Failed")], db_index=True, default="RECEIVED", max_length=16)),
                ("attempts", models.PositiveIntegerField(default=1)),
                ("last_error", models.TextField(blank=True, default="")),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-received_at"]},
        ),
        migrations.AddIndex(
            model_name="stripewebhookevent",
            index=models.Index(fields=["endpoint", "event_type", "status"], name="user_accoun_endpoin_4547cb_idx"),
        ),
    ]
