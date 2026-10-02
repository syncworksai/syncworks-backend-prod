from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("user_accounts", "0133_god_mode_user_intelligence_backlog"),
    ]

    operations = [
        migrations.CreateModel(
            name="FinanceIncomeSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=180)),
                ("kind", models.CharField(choices=[("PAYCHECK", "Paycheck"), ("BUSINESS", "Business"), ("RENTAL", "Rental income"), ("BENEFIT", "Benefit"), ("INVESTMENT", "Investment"), ("OTHER", "Other")], default="PAYCHECK", max_length=32)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("cadence", models.CharField(choices=[("WEEKLY", "Weekly"), ("BIWEEKLY", "Every two weeks"), ("SEMIMONTHLY", "Twice monthly"), ("MONTHLY", "Monthly"), ("QUARTERLY", "Quarterly"), ("ANNUAL", "Annual"), ("OTHER", "Other")], default="MONTHLY", max_length=32)),
                ("next_income_date", models.DateField(blank=True, null=True)),
                ("active", models.BooleanField(default=True)),
                ("is_manual", models.BooleanField(default=True)),
                ("notes", models.TextField(blank=True, default="")),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="finance_income_sources", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["next_income_date", "name"]},
        ),
        migrations.AlterField(
            model_name="financeobligation",
            name="category",
            field=models.CharField(choices=[("HOUSING", "Housing"), ("MORTGAGE", "Mortgage"), ("UTILITIES", "Utilities"), ("PHONE", "Phone"), ("INTERNET", "Internet"), ("INSURANCE", "Insurance"), ("VEHICLE", "Vehicle"), ("TRANSPORTATION", "Transportation"), ("GROCERIES", "Groceries"), ("SUBSCRIPTIONS", "Subscriptions"), ("DEBT", "Debt"), ("CHILDCARE", "Childcare"), ("HEALTH", "Health"), ("TAX", "Tax"), ("OTHER", "Other")], default="OTHER", max_length=32),
        ),
    ]
