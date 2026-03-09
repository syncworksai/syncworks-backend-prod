from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0053_salespipeline_is_locked_salesevent"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Invoice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(
                    choices=[("JOB", "Job Invoice"), ("CASH_FEE", "Cash Fee Invoice")],
                    default="JOB",
                    max_length=20
                )),
                ("status", models.CharField(
                    choices=[("OPEN", "Open"), ("PAID", "Paid"), ("OVERDUE", "Overdue"), ("VOID", "Void")],
                    default="OPEN",
                    max_length=20
                )),
                ("currency", models.CharField(default="usd", max_length=10)),
                ("amount_cents", models.PositiveIntegerField(default=0)),
                ("period_start", models.DateField(blank=True, null=True)),
                ("period_end", models.DateField(blank=True, null=True)),
                ("due_date", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("memo", models.CharField(blank=True, default="", max_length=255)),
                ("business", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="invoices",
                    to="user_accounts.business"
                )),
                ("created_by", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="created_invoices",
                    to=settings.AUTH_USER_MODEL
                )),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]