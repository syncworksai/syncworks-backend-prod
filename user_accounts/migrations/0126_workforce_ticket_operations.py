from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0125_professional_provider_resources"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkforceProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(blank=True, default="", max_length=120)),
                ("skills", models.JSONField(blank=True, default=list)),
                ("weekly_availability", models.JSONField(blank=True, default=dict)),
                ("breaks", models.JSONField(blank=True, default=list)),
                ("time_off", models.JSONField(blank=True, default=list)),
                ("default_buffer_minutes", models.PositiveIntegerField(default=0)),
                ("default_job_duration_minutes", models.PositiveIntegerField(default=60)),
                ("route_start_address", models.CharField(blank=True, default="", max_length=255)),
                ("is_schedulable", models.BooleanField(db_index=True, default=True)),
                ("notes", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("member", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="workforce_profile", to="user_accounts.businessmember")),
            ],
            options={"ordering": ["member__business_id", "member__user_id"]},
        ),
        migrations.CreateModel(
            name="TicketOperationalProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("origin", models.CharField(choices=[("MARKETPLACE", "SyncWorks Marketplace"), ("BUSINESS_ADDED", "Business-added customer"), ("IMPORTED", "Imported work"), ("INTERNAL", "Internal work")], db_index=True, default="BUSINESS_ADDED", max_length=24)),
                ("priority", models.CharField(choices=[("EMERGENCY", "Emergency"), ("URGENT", "Urgent"), ("STANDARD", "Standard"), ("FLEXIBLE", "Flexible")], db_index=True, default="STANDARD", max_length=20)),
                ("estimated_duration_minutes", models.PositiveIntegerField(default=60)),
                ("duration_low_minutes", models.PositiveIntegerField(default=30)),
                ("duration_high_minutes", models.PositiveIntegerField(default=120)),
                ("required_skills", models.JSONField(blank=True, default=list)),
                ("required_staff_count", models.PositiveIntegerField(default=1)),
                ("response_sla_minutes", models.PositiveIntegerField(default=0)),
                ("assignment_sla_minutes", models.PositiveIntegerField(default=0)),
                ("arrival_sla_minutes", models.PositiveIntegerField(default=0)),
                ("completion_sla_minutes", models.PositiveIntegerField(default=0)),
                ("expected_finish_at", models.DateTimeField(blank=True, null=True)),
                ("due_at", models.DateTimeField(blank=True, null=True)),
                ("customer_visible_note", models.TextField(blank=True, default="")),
                ("internal_note", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("ticket", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="operations_profile", to="user_accounts.ticket")),
            ],
            options={"ordering": ["-priority", "ticket_id"]},
        ),
        migrations.AddIndex(model_name="workforceprofile", index=models.Index(fields=["is_schedulable"], name="ua_workforce_sched_idx")),
        migrations.AddIndex(model_name="ticketoperationalprofile", index=models.Index(fields=["origin", "priority"], name="ua_ticketops_origin_pri_idx")),
        migrations.AddIndex(model_name="ticketoperationalprofile", index=models.Index(fields=["due_at"], name="ua_ticketops_due_idx")),
    ]
