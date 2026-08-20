from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0124_professional_services_scheduling"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProfessionalProvider",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160)),
                ("role_label", models.CharField(blank=True, default="", max_length=120)),
                ("active", models.BooleanField(default=True)),
                ("appointment_types", models.JSONField(blank=True, default=list)),
                ("weekly_schedule", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("practice", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="providers", to="user_accounts.professionalpracticeprofile")),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="ProfessionalResource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160)),
                ("resource_type", models.CharField(choices=[("ROOM", "Room"), ("CHAIR", "Chair"), ("EQUIPMENT", "Equipment"), ("OTHER", "Other")], default="ROOM", max_length=24)),
                ("active", models.BooleanField(default=True)),
                ("appointment_types", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("practice", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="resources", to="user_accounts.professionalpracticeprofile")),
            ],
            options={"ordering": ["resource_type", "name"]},
        ),
        migrations.AddField(model_name="professionalappointment", name="provider", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="appointments", to="user_accounts.professionalprovider")),
        migrations.AddField(model_name="professionalappointment", name="resource", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="appointments", to="user_accounts.professionalresource")),
    ]
