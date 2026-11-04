from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [("pm_workspace", "0016_rename_pm_workspac_workspa_b98aec_idx_pm_workspac_workspa_7e7235_idx_and_more")]
    operations = [migrations.CreateModel(
        name="PMLeadSubscription",
        fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("stripe_customer_id", models.CharField(blank=True, default="", max_length=128)),
            ("stripe_subscription_id", models.CharField(blank=True, db_index=True, default="", max_length=128)),
            ("stripe_checkout_session_id", models.CharField(blank=True, default="", max_length=128)),
            ("status", models.CharField(default="NONE", max_length=24)),
            ("mailbox_count", models.PositiveSmallIntegerField(default=1)),
            ("features", models.JSONField(blank=True, default=list)),
            ("monthly_cents", models.PositiveIntegerField(default=0)),
            ("discount_percent", models.PositiveSmallIntegerField(default=0)),
            ("current_period_end", models.DateTimeField(blank=True, null=True)),
            ("cancel_at_period_end", models.BooleanField(default=False)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("workspace", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="lead_subscription", to="pm_workspace.pmworkspace")),
        ],
    )]
