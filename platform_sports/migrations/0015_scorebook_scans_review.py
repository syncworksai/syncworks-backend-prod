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
            name="SportsScorebookPage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("side", models.CharField(choices=[("TEAM", "Our team"), ("OPPONENT", "Opponent")], max_length=12)),
                ("page_order", models.PositiveSmallIntegerField(default=1)),
                ("filename", models.CharField(blank=True, max_length=160)),
                ("rotation", models.PositiveSmallIntegerField(default=0)),
                ("source_sha256", models.CharField(max_length=64)),
                ("image_mime", models.CharField(default="image/jpeg", max_length=32)),
                ("image_data", models.BinaryField(repr=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("game", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="scorebook_pages", to="platform_sports.sportsgame")),
                ("uploaded_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sports_scorebook_uploads", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("page_order", "id"),
                "constraints": [
                    models.UniqueConstraint(fields=("game", "source_sha256"), name="sports_unique_scorebook_scan"),
                ],
            },
        ),
        migrations.CreateModel(
            name="SportsScorebookReview",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("DRAFT", "Needs review"), ("SCORE_VERIFIED", "Final score verified"), ("FULLY_VERIFIED", "All plays verified")], default="DRAFT", max_length=20)),
                ("applied_sha256", models.CharField(blank=True, max_length=64)),
                ("audit_log", models.JSONField(blank=True, default=list)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("game", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="scorebook_review", to="platform_sports.sportsgame")),
                ("updated_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sports_scorebook_reviews", to=settings.AUTH_USER_MODEL)),
                ("verified_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sports_scorebooks_verified", to=settings.AUTH_USER_MODEL)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
