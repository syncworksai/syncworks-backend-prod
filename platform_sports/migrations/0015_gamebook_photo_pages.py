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
            name="SportsGameBookPage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("page_number", models.PositiveSmallIntegerField()),
                ("image_data", models.BinaryField(editable=False)),
                ("image_mime", models.CharField(max_length=32)),
                ("image_width", models.PositiveIntegerField()),
                ("image_height", models.PositiveIntegerField()),
                ("original_filename", models.CharField(max_length=180)),
                ("notes", models.CharField(blank=True, max_length=1000)),
                ("review_status", models.CharField(
                    choices=[("NEEDS_REVIEW", "Needs review"), ("REVIEWED", "Image reviewed")],
                    default="NEEDS_REVIEW", max_length=16,
                )),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("game", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="scorebook_pages", to="platform_sports.sportsgame",
                )),
                ("uploaded_by", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="uploaded_gamebook_pages", to=settings.AUTH_USER_MODEL,
                )),
                ("reviewed_by", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="reviewed_gamebook_pages", to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ("page_number", "id")},
        ),
        migrations.AddConstraint(
            model_name="sportsgamebookpage",
            constraint=models.UniqueConstraint(
                fields=("game", "page_number"), name="sports_book_game_page",
            ),
        ),
    ]
