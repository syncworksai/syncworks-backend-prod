from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0030_execution_totals_seed_bed_springs"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SportsPlayerQABTotal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("season_name", models.CharField(blank=True, max_length=80)),
                ("points", models.DecimalField(decimal_places=2, default=0, max_digits=8)),
                ("note", models.CharField(blank=True, max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="way_qab_totals", to="platform_sports.sportsplayer")),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="way_qab_totals", to="platform_sports.sportsteam")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sports_qab_totals_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("player__display_name", "id")},
        ),
        migrations.AddConstraint(
            model_name="sportsplayerqabtotal",
            constraint=models.UniqueConstraint(fields=("team", "player", "season_name"), name="sports_unique_qab_total_season"),
        ),
        migrations.AddIndex(
            model_name="sportsplayerqabtotal",
            index=models.Index(fields=["team", "season_name"], name="sports_qab_total_season"),
        ),
    ]
