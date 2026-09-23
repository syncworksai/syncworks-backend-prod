from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0014_sports_team_badge_rules"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SportsGameBookPhoto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("original_name", models.CharField(blank=True, max_length=220)),
                ("content_type", models.CharField(default="image/jpeg", max_length=80)),
                ("byte_size", models.PositiveIntegerField(default=0)),
                ("sha256", models.CharField(max_length=64)),
                ("image_data", models.BinaryField()),
                ("page_label", models.CharField(blank=True, max_length=80)),
                ("review_status", models.CharField(choices=[("UPLOADED", "Uploaded"), ("REVIEWED", "Reviewed"), ("VERIFIED", "Verified")], default="UPLOADED", max_length=12)),
                ("review_notes", models.TextField(blank=True)),
                ("extracted_data", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("game", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="book_photos", to="platform_sports.sportsgame")),
                ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sports_game_book_photos_uploaded", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("created_at", "id")},
        ),
        migrations.AddConstraint(
            model_name="sportsgamebookphoto",
            constraint=models.UniqueConstraint(fields=("game", "sha256"), name="sports_unique_book_photo_hash"),
        ),
    ]
