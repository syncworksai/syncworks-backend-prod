import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0115_cross_business_partner_tickets"),
    ]

    operations = [
        migrations.CreateModel(
            name="PartnerWorkEstimate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("revision", models.PositiveIntegerField(default=1)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("SUBMITTED", "Submitted"), ("APPROVED", "Approved"), ("REJECTED", "Rejected"), ("WITHDRAWN", "Withdrawn"), ("SUPERSEDED", "Superseded")], db_index=True, default="DRAFT", max_length=20)),
                ("title", models.CharField(blank=True, default="", max_length=200)),
                ("scope", models.TextField(blank=True, default="")),
                ("line_items", models.JSONField(blank=True, default=list)),
                ("subtotal_cents", models.PositiveBigIntegerField(default=0)),
                ("tax_cents", models.PositiveBigIntegerField(default=0)),
                ("total_cents", models.PositiveBigIntegerField(default=0)),
                ("estimated_days", models.PositiveIntegerField(blank=True, null=True)),
                ("valid_until", models.DateField(blank=True, null=True)),
                ("partner_notes", models.TextField(blank=True, default="")),
                ("hiring_business_notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_estimates_created", to=settings.AUTH_USER_MODEL)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_estimates_reviewed", to=settings.AUTH_USER_MODEL)),
                ("work_ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="estimates", to="user_accounts.partnerworkticket")),
            ],
            options={"ordering": ["-revision", "-id"]},
        ),
        migrations.CreateModel(
            name="PartnerWorkChangeOrder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sequence", models.PositiveIntegerField(default=1)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("SUBMITTED", "Submitted"), ("APPROVED", "Approved"), ("REJECTED", "Rejected"), ("CANCELLED", "Cancelled")], db_index=True, default="DRAFT", max_length=20)),
                ("title", models.CharField(max_length=200)),
                ("reason", models.TextField(blank=True, default="")),
                ("scope_delta", models.TextField(blank=True, default="")),
                ("line_items", models.JSONField(blank=True, default=list)),
                ("partner_amount_delta_cents", models.BigIntegerField(default=0)),
                ("customer_amount_delta_cents", models.BigIntegerField(default=0)),
                ("schedule_days_delta", models.IntegerField(default=0)),
                ("partner_notes", models.TextField(blank=True, default="")),
                ("hiring_business_notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_change_orders_created", to=settings.AUTH_USER_MODEL)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="partner_change_orders_reviewed", to=settings.AUTH_USER_MODEL)),
                ("work_ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="change_orders", to="user_accounts.partnerworkticket")),
            ],
            options={"ordering": ["-sequence", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="partnerworkestimate",
            constraint=models.UniqueConstraint(fields=("work_ticket", "revision"), name="ua_unique_partner_estimate_revision"),
        ),
        migrations.AddConstraint(
            model_name="partnerworkchangeorder",
            constraint=models.UniqueConstraint(fields=("work_ticket", "sequence"), name="ua_unique_partner_change_sequence"),
        ),
        migrations.AddIndex(
            model_name="partnerworkestimate",
            index=models.Index(fields=["work_ticket", "status", "created_at"], name="ua_pestimate_work_status_idx"),
        ),
        migrations.AddIndex(
            model_name="partnerworkchangeorder",
            index=models.Index(fields=["work_ticket", "status", "created_at"], name="ua_pchange_work_status_idx"),
        ),
    ]
