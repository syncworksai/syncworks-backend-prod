from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("user_accounts", "0123_identity_trust_location"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProfessionalPracticeProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("practice_type", models.CharField(choices=[("DENTAL", "Dentist / Dental practice"), ("OPTOMETRY", "Optometrist / Eye care"), ("CHIROPRACTIC", "Chiropractic"), ("PHYSICAL_THERAPY", "Physical therapy"), ("VETERINARY", "Veterinary"), ("MED_SPA", "Med spa"), ("OTHER", "Other appointment business")], db_index=True, default="DENTAL", max_length=32)),
                ("scheduling_enabled", models.BooleanField(default=True)),
                ("accepting_new_patients", models.BooleanField(default=True)),
                ("accepted_insurance", models.JSONField(blank=True, default=list)),
                ("appointment_types", models.JSONField(blank=True, default=list)),
                ("weekly_schedule", models.JSONField(blank=True, default=dict)),
                ("booking_lead_minutes", models.PositiveIntegerField(default=60)),
                ("booking_buffer_minutes", models.PositiveIntegerField(default=0)),
                ("scheduling_disclaimer", models.CharField(blank=True, default="Insurance participation is supplied by the practice. Confirm coverage with the practice or insurer before care.", max_length=280)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="professional_practice", to="user_accounts.business")),
            ],
            options={"ordering": ["business__name"]},
        ),
        migrations.CreateModel(
            name="ProfessionalAppointment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("appointment_type", models.CharField(blank=True, default="Appointment", max_length=120)),
                ("status", models.CharField(choices=[("REQUESTED", "Requested"), ("PROPOSED", "Proposed"), ("ACCEPTED", "Accepted"), ("DECLINED", "Declined"), ("RESCHEDULE_REQUESTED", "Reschedule requested"), ("CANCELLED", "Cancelled"), ("COMPLETED", "Completed")], db_index=True, default="REQUESTED", max_length=32)),
                ("proposed_start", models.DateTimeField(blank=True, null=True)),
                ("proposed_end", models.DateTimeField(blank=True, null=True)),
                ("preferred_windows", models.JSONField(blank=True, default=list)),
                ("location", models.CharField(blank=True, default="", max_length=240)),
                ("insurance_plan", models.CharField(blank=True, default="", max_length=120)),
                ("scheduling_note", models.TextField(blank=True, default="")),
                ("reschedule_note", models.TextField(blank=True, default="")),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="professional_appointments", to="user_accounts.business")),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="professional_appointments", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-proposed_start", "-created_at"]},
        ),
        migrations.AddIndex(
            model_name="professionalappointment",
            index=models.Index(fields=["business", "status"], name="ua_prof_biz_status_idx"),
        ),
        migrations.AddIndex(
            model_name="professionalappointment",
            index=models.Index(fields=["customer", "status"], name="ua_prof_cust_status_idx"),
        ),
    ]
