from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0134_finance_income_and_expense_categories"),
    ]

    operations = [
        migrations.CreateModel(
            name="FinanceDebtPayment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("payment_date", models.DateField()),
                ("source", models.CharField(choices=[("MANUAL", "Manual"), ("PLAID", "Connected account"), ("IMPORTED", "Imported")], default="MANUAL", max_length=24)),
                ("status", models.CharField(choices=[("POSTED", "Posted"), ("PENDING", "Pending"), ("REVERSED", "Reversed")], default="POSTED", max_length=24)),
                ("balance_before", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ("balance_after", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ("principal_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ("interest_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ("fee_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ("estimated_interest_saved_next_30_days", models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ("provider_reference", models.CharField(blank=True, default="", max_length=255)),
                ("notes", models.TextField(blank=True, default="")),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="debt_payments", to="user_accounts.financeaccount")),
                ("funding_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="funded_debt_payments", to="user_accounts.financeaccount")),
                ("liability", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payments", to="user_accounts.financeliability")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="finance_debt_payments", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-payment_date", "-id"]},
        ),
        migrations.AddIndex(
            model_name="financedebtpayment",
            index=models.Index(fields=["user", "-payment_date"], name="user_accoun_user_id_74ceca_idx"),
        ),
        migrations.AddIndex(
            model_name="financedebtpayment",
            index=models.Index(fields=["liability", "-payment_date"], name="user_accoun_liabili_755b2b_idx"),
        ),
        migrations.AddConstraint(
            model_name="financedebtpayment",
            constraint=models.UniqueConstraint(condition=~models.Q(("provider_reference", "")), fields=("user", "provider_reference"), name="uniq_user_finance_debt_payment_provider_ref"),
        ),
    ]
