from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0121_personal_finance_foundation"),
    ]

    operations = [
        migrations.CreateModel(
            name="FinanceBudget",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=180)),
                ("category", models.CharField(max_length=100)),
                ("monthly_limit", models.DecimalField(decimal_places=2, max_digits=14)),
                ("active", models.BooleanField(default=True)),
                ("priority", models.PositiveSmallIntegerField(default=1)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="finance_budgets", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["priority", "category", "name"]},
        ),
        migrations.AddConstraint(
            model_name="financebudget",
            constraint=models.UniqueConstraint(fields=("user", "category"), name="uniq_user_finance_budget_category"),
        ),
    ]
