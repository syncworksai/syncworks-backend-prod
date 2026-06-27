from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0103_trackable_assets"),
    ]

    operations = [
        migrations.CreateModel(
            name="BusinessResource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160)),
                ("resource_type", models.CharField(choices=[("BAY", "Bay"), ("TRUCK", "Truck"), ("CREW", "Crew"), ("STATION", "Station"), ("ROOM", "Room"), ("TABLE", "Table"), ("SHELF", "Shelf"), ("MACHINE", "Machine"), ("REGISTER", "Register"), ("HOLDING_AREA", "Holding Area"), ("TOOL", "Tool"), ("CUSTOM", "Custom")], default="CUSTOM", max_length=24)),
                ("status", models.CharField(choices=[("AVAILABLE", "Available"), ("OCCUPIED", "Occupied"), ("RESERVED", "Reserved"), ("UNAVAILABLE", "Unavailable"), ("MAINTENANCE", "Maintenance"), ("INACTIVE", "Inactive")], default="AVAILABLE", max_length=24)),
                ("location", models.CharField(blank=True, default="", max_length=160)),
                ("capacity", models.PositiveIntegerField(default=1)),
                ("skills", models.JSONField(blank=True, default=list)),
                ("availability", models.JSONField(blank=True, default=dict)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="operational_resources", to="user_accounts.business")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="business_resources_created", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["resource_type", "name", "id"]},
        ),
        migrations.CreateModel(
            name="ResourceAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("PLANNED", "Planned"), ("ACTIVE", "Active"), ("COMPLETED", "Completed"), ("CANCELLED", "Cancelled")], default="PLANNED", max_length=20)),
                ("starts_at", models.DateTimeField(blank=True, null=True)),
                ("ends_at", models.DateTimeField(blank=True, null=True)),
                ("notes", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assigned_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="resource_assignments_created", to=settings.AUTH_USER_MODEL)),
                ("resource", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assignments", to="user_accounts.businessresource")),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="resource_assignments", to="user_accounts.ticket")),
            ],
            options={"ordering": ["starts_at", "id"]},
        ),
        migrations.CreateModel(
            name="ResourceMovement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("from_location", models.CharField(blank=True, default="", max_length=160)),
                ("to_location", models.CharField(max_length=160)),
                ("reason", models.CharField(blank=True, default="", max_length=255)),
                ("moved_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("asset", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="resource_movements", to="user_accounts.trackableasset")),
                ("moved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="resource_movements_created", to=settings.AUTH_USER_MODEL)),
                ("resource", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="movements", to="user_accounts.businessresource")),
                ("ticket", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="resource_movements", to="user_accounts.ticket")),
            ],
            options={"ordering": ["-moved_at", "-id"]},
        ),
        migrations.AddConstraint(model_name="businessresource", constraint=models.UniqueConstraint(fields=("business", "name"), name="ua_business_resource_name_unique")),
        migrations.AddIndex(model_name="businessresource", index=models.Index(fields=["business", "resource_type", "is_active"], name="ua_resource_business_type_idx")),
        migrations.AddIndex(model_name="businessresource", index=models.Index(fields=["business", "status"], name="ua_res_business_status_idx")),
        migrations.AddConstraint(model_name="resourceassignment", constraint=models.UniqueConstraint(condition=models.Q(("status__in", ["PLANNED", "ACTIVE"])), fields=("resource", "ticket"), name="ua_resource_ticket_open_unique")),
        migrations.AddIndex(model_name="resourceassignment", index=models.Index(fields=["resource", "status", "starts_at"], name="ua_res_assign_status_idx")),
        migrations.AddIndex(model_name="resourceassignment", index=models.Index(fields=["ticket", "status"], name="ua_ticket_resource_status_idx")),
        migrations.AddIndex(model_name="resourcemovement", index=models.Index(fields=["resource", "moved_at"], name="ua_resource_movement_time_idx")),
        migrations.AddIndex(model_name="resourcemovement", index=models.Index(fields=["asset", "moved_at"], name="ua_asset_movement_time_idx")),
    ]
