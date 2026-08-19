from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0122_finance_budget_decision_engine"),
    ]

    operations = [
        migrations.CreateModel(
            name="PersonalIdentity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_name", models.CharField(blank=True, default="", max_length=120)),
                ("phone", models.CharField(blank=True, default="", max_length=32)),
                ("bio", models.CharField(blank=True, default="", max_length=500)),
                ("public_city", models.CharField(blank=True, default="", max_length=80)),
                ("public_state", models.CharField(blank=True, default="", max_length=32)),
                ("profile_photo", models.ImageField(blank=True, null=True, upload_to="identity/profile_photos/")),
                ("show_photo_services", models.BooleanField(default=True)),
                ("show_photo_social", models.BooleanField(default=True)),
                ("show_photo_groups", models.BooleanField(default=True)),
                ("show_city_public", models.BooleanField(default=False)),
                ("use_current_for_weather", models.BooleanField(default=True)),
                ("use_current_for_traffic", models.BooleanField(default=True)),
                ("use_current_for_nearby", models.BooleanField(default=True)),
                ("use_current_for_local_info", models.BooleanField(default=True)),
                ("onboarding_completed", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="personal_identity", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="UserLocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("HOME", "Home"), ("WORK", "Work"), ("SAVED", "Saved place")], default="SAVED", max_length=16)),
                ("label", models.CharField(blank=True, default="", max_length=80)),
                ("address_line1", models.CharField(max_length=220)),
                ("address_line2", models.CharField(blank=True, default="", max_length=120)),
                ("city", models.CharField(blank=True, default="", max_length=100)),
                ("state", models.CharField(blank=True, default="", max_length=80)),
                ("postal_code", models.CharField(blank=True, default="", max_length=20)),
                ("country", models.CharField(blank=True, default="US", max_length=2)),
                ("latitude", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("longitude", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("is_default_service", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="saved_locations", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-is_default_service", "kind", "label", "id"]},
        ),
        migrations.CreateModel(
            name="BusinessVerification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("UNVERIFIED", "Unverified"), ("IN_REVIEW", "In review"), ("VERIFIED", "Verified"), ("REJECTED", "Rejected")], default="UNVERIFIED", max_length=20)),
                ("email_verified", models.BooleanField(default=False)),
                ("phone_verified", models.BooleanField(default=False)),
                ("identity_verified", models.BooleanField(default=False)),
                ("business_details_verified", models.BooleanField(default=False)),
                ("payment_verified", models.BooleanField(default=False)),
                ("license_verified", models.BooleanField(default=False)),
                ("insurance_verified", models.BooleanField(default=False)),
                ("background_verified", models.BooleanField(default=False)),
                ("review_notes", models.TextField(blank=True, default="")),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="verification", to="user_accounts.business")),
            ],
        ),
        migrations.AddIndex(
            model_name="userlocation",
            index=models.Index(fields=["user", "kind"], name="user_accoun_user_id_86e4af_idx"),
        ),
        migrations.AddIndex(
            model_name="userlocation",
            index=models.Index(fields=["user", "is_default_service"], name="user_accoun_user_id_451794_idx"),
        ),
    ]
