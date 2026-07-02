import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("user_accounts", "0112_execute_historical_imports")]
    operations = [
        migrations.CreateModel(
            name="BusinessProject",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True, default="")),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("ACTIVE", "Active"), ("ON_HOLD", "On hold"), ("COMPLETED", "Completed"), ("CANCELLED", "Cancelled")], db_index=True, default="DRAFT", max_length=20)),
                ("billing_mode", models.CharField(choices=[("COMBINED", "Combined invoice"), ("SEPARATE", "Separate child invoices"), ("MILESTONE", "Milestone billing")], default="COMBINED", max_length=20)),
                ("progress_mode", models.CharField(choices=[("EQUAL", "Equal child weighting"), ("WEIGHTED", "Custom child weighting")], default="EQUAL", max_length=20)),
                ("customer_status_note", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="projects", to="user_accounts.business")),
                ("business_customer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="projects", to="user_accounts.businesscustomer")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="business_projects_created", to=settings.AUTH_USER_MODEL)),
                ("primary_ticket", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="primary_for_projects", to="user_accounts.ticket")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="business_projects_updated", to=settings.AUTH_USER_MODEL)),
            ], options={"ordering": ["-updated_at", "-id"]},
        ),
        migrations.AddField(model_name="ticket", name="actual_cost_cents", field=models.PositiveBigIntegerField(default=0)),
        migrations.AddField(model_name="ticket", name="actual_customer_amount_cents", field=models.PositiveBigIntegerField(default=0)),
        migrations.AddField(model_name="ticket", name="customer_status_label", field=models.CharField(blank=True, default="", max_length=160)),
        migrations.AddField(model_name="ticket", name="customer_visible", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="ticket", name="parent_ticket", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="child_tickets", to="user_accounts.ticket")),
        migrations.AddField(model_name="ticket", name="progress_weight", field=models.PositiveIntegerField(default=1)),
        migrations.AddField(model_name="ticket", name="project", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="tickets", to="user_accounts.businessproject")),
        migrations.AddField(model_name="ticket", name="projected_cost_cents", field=models.PositiveBigIntegerField(default=0)),
        migrations.AddField(model_name="ticket", name="projected_customer_amount_cents", field=models.PositiveBigIntegerField(default=0)),
        migrations.AddField(model_name="ticket", name="work_scope", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="ticket", name="work_title", field=models.CharField(blank=True, default="", max_length=200)),
        migrations.AddIndex(model_name="businessproject", index=models.Index(fields=["business", "status", "updated_at"], name="ua_project_biz_status_idx")),
        migrations.AddIndex(model_name="businessproject", index=models.Index(fields=["business", "business_customer", "updated_at"], name="ua_project_customer_idx")),
        migrations.AddIndex(model_name="ticket", index=models.Index(fields=["project", "status", "created_at"], name="ua_ticket_project_status_idx")),
        migrations.AddIndex(model_name="ticket", index=models.Index(fields=["parent_ticket", "created_at"], name="ua_ticket_parent_idx")),
    ]
