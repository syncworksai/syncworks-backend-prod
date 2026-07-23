from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="HealthAthleteProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date_of_birth", models.DateField(blank=True, null=True)),
                ("age_group", models.CharField(choices=[("unknown", "Unknown"), ("child", "Child"), ("teen", "Teen"), ("young_adult", "Young adult"), ("adult", "Adult"), ("masters", "Masters"), ("older_adult", "Older adult")], default="unknown", max_length=24)),
                ("primary_sport", models.CharField(default="General Fitness", max_length=120)),
                ("training_experience", models.CharField(choices=[("beginner", "Beginner"), ("intermediate", "Intermediate"), ("advanced", "Advanced")], default="beginner", max_length=24)),
                ("measurements", models.JSONField(blank=True, default=dict)),
                ("plan_preferences", models.JSONField(blank=True, default=dict)),
                ("simulation_preferences", models.JSONField(blank=True, default=dict)),
                ("requires_plan_review", models.BooleanField(default=False)),
                ("profile_version", models.PositiveIntegerField(default=1)),
                ("last_plan_reset_at", models.DateTimeField(blank=True, null=True)),
                ("last_plan_restart_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="health_athlete_profile", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-updated_at",)},
        ),
    ]
