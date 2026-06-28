from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0104_business_resources"),
    ]

    operations = [
        migrations.CreateModel(
            name="TicketRequirement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("requirement_type", models.CharField(choices=[("CUSTOMER_APPROVAL", "Customer Approval"), ("CUSTOMER_RESPONSE", "Customer Response"), ("PAYMENT", "Payment"), ("DOCUMENT", "Document"), ("PART", "Part or Material"), ("ASSET", "Asset"), ("RESOURCE", "Resource"), ("STAFF", "Staff"), ("INSPECTION", "Inspection"), ("EXTERNAL", "External Dependency"), ("CUSTOM", "Custom")], default="CUSTOM", max_length=32)),
                ("title", models.CharField(max_length=180)),
                ("description", models.TextField(blank=True, default="")),
                ("status", models.CharField(choices=[("OPEN", "Open"), ("SATISFIED", "Satisfied"), ("WAIVED", "Waived"), ("CANCELLED", "Cancelled")], default="OPEN", max_length=20)),
                ("severity", models.CharField(choices=[("LOW", "Low"), ("NORMAL", "Normal"), ("HIGH", "High"), ("CRITICAL", "Critical")], default="NORMAL", max_length=16)),
                ("blocks_progress", models.BooleanField(default=True)),
                ("due_at", models.DateTimeField(blank=True, null=True)),
                ("satisfied_at", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("asset", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ticket_requirements", to="user_accounts.trackableasset")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ticket_requirements_created", to=settings.AUTH_USER_MODEL)),
                ("resource", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ticket_requirements", to="user_accounts.businessresource")),
                ("satisfied_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ticket_requirements_satisfied", to=settings.AUTH_USER_MODEL)),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="requirements", to="user_accounts.ticket")),
            ],
            options={"ordering": ["-blocks_progress", "due_at", "id"]},
        ),
        migrations.CreateModel(
            name="TicketDependency",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("description", models.CharField(blank=True, default="", max_length=255)),
                ("is_blocking", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ticket_dependencies_created", to=settings.AUTH_USER_MODEL)),
                ("depends_on_ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="dependent_tickets", to="user_accounts.ticket")),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="dependencies", to="user_accounts.ticket")),
            ],
            options={"ordering": ["ticket_id", "id"]},
        ),
        migrations.AddIndex(model_name="ticketrequirement", index=models.Index(fields=["ticket", "status", "blocks_progress"], name="ua_req_ticket_status_idx")),
        migrations.AddIndex(model_name="ticketrequirement", index=models.Index(fields=["status", "severity", "due_at"], name="ua_req_priority_idx")),
        migrations.AddConstraint(model_name="ticketdependency", constraint=models.UniqueConstraint(fields=("ticket", "depends_on_ticket"), name="ua_ticket_dependency_unique")),
        migrations.AddConstraint(model_name="ticketdependency", constraint=models.CheckConstraint(condition=models.Q(("ticket", models.F("depends_on_ticket")), _negated=True), name="ua_ticket_no_self_dependency")),
        migrations.AddIndex(model_name="ticketdependency", index=models.Index(fields=["ticket", "is_blocking"], name="ua_ticket_dependency_idx")),
    ]
