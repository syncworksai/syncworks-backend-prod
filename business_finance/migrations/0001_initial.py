from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("user_accounts", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BusinessExpense",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(max_length=20, default="OTHER", choices=[("LABOR","Labor"),("MATERIAL","Materials"),("SUBCONTRACTOR","Subcontractor"),("OVERHEAD","Overhead"),("EQUIPMENT","Equipment"),("MARKETING","Marketing"),("OTHER","Other")])),
                ("status", models.CharField(max_length=12, default="INCURRED", choices=[("PLANNED","Planned"),("INCURRED","Incurred"),("PAID","Paid"),("VOID","Void")])),
                ("description", models.CharField(max_length=220)),
                ("vendor", models.CharField(max_length=160, blank=True, default="")),
                ("quantity", models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("1.00"))),
                ("unit_cost", models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))),
                ("amount", models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"), editable=False)),
                ("incurred_on", models.DateField(default=django.utils.timezone.localdate)),
                ("due_on", models.DateField(blank=True, null=True)),
                ("paid_on", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="finance_expenses", to="user_accounts.business")),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.SET_NULL, blank=True, null=True, related_name="finance_costs", to="user_accounts.ticket")),
                ("created_by", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.SET_NULL, blank=True, null=True, related_name="business_finance_expenses_created")),
            ],
            options={"ordering": ["-incurred_on", "-id"], "indexes": [
                models.Index(fields=["business", "incurred_on"], name="bf_exp_business_date"),
                models.Index(fields=["business", "ticket"], name="bf_exp_business_job"),
            ]},
        ),
        migrations.CreateModel(
            name="JobCostReview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("costs_complete", models.BooleanField(default=False)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="finance_job_reviews", to="user_accounts.business")),
                ("ticket", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="finance_cost_review", to="user_accounts.ticket")),
                ("reviewed_by", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.SET_NULL, blank=True, null=True)),
            ],
            options={"ordering": ["-reviewed_at", "-id"]},
        ),
        migrations.CreateModel(
            name="BusinessFinanceSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("opening_cash_balance", models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)),
                ("opening_cash_date", models.DateField(blank=True, null=True)),
                ("expenses_reconciled_through", models.DateField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="finance_settings", to="user_accounts.business")),
                ("updated_by", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.SET_NULL, blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name="CashForecastItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("description", models.CharField(max_length=220)),
                ("direction", models.CharField(max_length=3, choices=[("IN","Expected inflow"),("OUT","Expected outflow")])),
                ("status", models.CharField(max_length=12, default="PLANNED", choices=[("PLANNED","Planned"),("SETTLED","Settled elsewhere"),("CANCELLED","Cancelled")])),
                ("amount", models.DecimalField(max_digits=14, decimal_places=2)),
                ("expected_on", models.DateField()),
                ("notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="cash_forecast_items", to="user_accounts.business")),
                ("created_by", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.SET_NULL, blank=True, null=True)),
            ],
            options={"ordering": ["expected_on", "id"], "indexes": [models.Index(fields=["business", "expected_on"], name="bf_forecast_business_day")]},
        ),
    ]
