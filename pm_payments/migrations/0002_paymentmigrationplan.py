from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("pm_payments", "0001_initial"),
        ("user_accounts", "0137_business_pilot_tracking"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentMigrationPlan",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("business", models.OneToOneField(
                    to="user_accounts.business", on_delete=django.db.models.deletion.CASCADE,
                    related_name="payment_migration",
                )),
                ("workspace_reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("current_processor", models.CharField(blank=True, default="", max_length=100)),
                ("current_monthly_fees", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("current_monthly_transactions", models.PositiveIntegerField(blank=True, null=True)),
                ("monthly_other_provider_costs", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("monthly_returned_payments", models.PositiveIntegerField(blank=True, null=True)),
                ("monthly_unmatched_deposits", models.PositiveIntegerField(blank=True, null=True)),
                ("average_payout_days", models.DecimalField(blank=True, decimal_places=1, max_digits=6, null=True)),
                ("monthly_reconciliation_hours", models.DecimalField(blank=True, decimal_places=1, max_digits=6, null=True)),
                ("costs_reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("test_evidence", models.JSONField(blank=True, default=dict)),
                ("test_notes", models.TextField(blank=True, default="")),
                ("test_review_requested_at", models.DateTimeField(blank=True, null=True)),
                ("founder_test_reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("founder_test_reviewer_id", models.PositiveIntegerField(blank=True, null=True)),
                ("founder_test_notes", models.TextField(blank=True, default="")),
                ("switch_requested_at", models.DateTimeField(blank=True, null=True)),
                ("updated_by_id", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
