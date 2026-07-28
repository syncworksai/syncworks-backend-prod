import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="PMWorkspace",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=180)),
                ("manager_name", models.CharField(blank=True, max_length=180)),
                ("phone", models.CharField(blank=True, max_length=40)),
                ("office_email", models.EmailField(blank=True, max_length=254)),
                ("tenant_email", models.EmailField(blank=True, max_length=254)),
                ("reply_to_email", models.EmailField(blank=True, max_length=254)),
                ("sender_name", models.CharField(blank=True, max_length=180)),
                ("website", models.URLField(blank=True)),
                ("office_address", models.CharField(blank=True, max_length=255)),
                ("email_signature", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="pm_workspaces", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["name", "id"]},
        ),
        migrations.CreateModel(
            name="PMTenant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("first_name", models.CharField(max_length=100)),
                ("last_name", models.CharField(blank=True, max_length=100)),
                ("email", models.EmailField(max_length=254)),
                ("phone", models.CharField(blank=True, max_length=40)),
                ("property_name", models.CharField(blank=True, max_length=180)),
                ("unit_label", models.CharField(blank=True, max_length=80)),
                ("move_in_date", models.DateField(blank=True, null=True)),
                ("lease_start", models.DateField(blank=True, null=True)),
                ("lease_end", models.DateField(blank=True, null=True)),
                ("monthly_rent", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("notes", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("INVITE_PENDING", "Invite pending"), ("CONNECTED", "Connected"), ("INACTIVE", "Inactive")], default="DRAFT", max_length=24)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_pm_tenants", to=settings.AUTH_USER_MODEL)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="pm_tenant_records", to=settings.AUTH_USER_MODEL)),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tenants", to="pm_workspace.pmworkspace")),
            ],
            options={"ordering": ["last_name", "first_name", "id"]},
        ),
        migrations.CreateModel(
            name="PMTenantInvitation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mode", models.CharField(choices=[("COMPLETE_RECORD", "PM completed tenant record"), ("TENANT_ONBOARDING", "Tenant completes onboarding")], default="COMPLETE_RECORD", max_length=24)),
                ("code", models.CharField(editable=False, max_length=32, unique=True)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("ACCEPTED", "Accepted"), ("REVOKED", "Revoked"), ("EXPIRED", "Expired")], default="PENDING", max_length=16)),
                ("expires_at", models.DateTimeField()),
                ("sent_to_email", models.EmailField(max_length=254)),
                ("sent_from_name", models.CharField(blank=True, max_length=180)),
                ("reply_to_email", models.EmailField(blank=True, max_length=254)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="invitations", to="pm_workspace.pmtenant")),
            ],
        ),
        migrations.AddConstraint(
            model_name="pmtenant",
            constraint=models.UniqueConstraint(fields=("workspace", "email"), name="uniq_pm_workspace_tenant_email"),
        ),
    ]
