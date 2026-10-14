from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0028_enable_bed_springs_way_we_play"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SportsPlayerMetricRating",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("metric_key", models.CharField(choices=[("PLAYER_GRADE", "Coach Grade"), ("PLATE_APPROACH", "Plate Approach"), ("EXECUTION", "Execution")], max_length=32)),
                ("value", models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(10)])),
                ("period_key", models.CharField(default="CURRENT", max_length=32)),
                ("week_of", models.DateField(blank=True, null=True)),
                ("note", models.CharField(blank=True, max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="way_metric_ratings", to="platform_sports.sportsplayer")),
                ("rated_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sports_way_ratings_given", to=settings.AUTH_USER_MODEL)),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="way_metric_ratings", to="platform_sports.sportsteam")),
            ],
            options={"ordering": ("player__display_name", "metric_key", "period_key")},
        ),
        migrations.CreateModel(
            name="SportsTeamWeekMetric",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("week_of", models.DateField()),
                ("expected_runs_per_game", models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ("note", models.CharField(blank=True, max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="way_week_metrics", to="platform_sports.sportsteam")),
                ("updated_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sports_way_week_metrics_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("week_of", "id")},
        ),
        migrations.AddConstraint(
            model_name="sportsplayermetricrating",
            constraint=models.UniqueConstraint(fields=("team", "player", "metric_key", "period_key"), name="sports_unique_way_metric_period"),
        ),
        migrations.AddIndex(
            model_name="sportsplayermetricrating",
            index=models.Index(fields=["team", "period_key"], name="sports_way_rating_period"),
        ),
        migrations.AddIndex(
            model_name="sportsplayermetricrating",
            index=models.Index(fields=["player", "metric_key"], name="sports_way_rating_player"),
        ),
        migrations.AddConstraint(
            model_name="sportsteamweekmetric",
            constraint=models.UniqueConstraint(fields=("team", "week_of"), name="sports_unique_way_team_week"),
        ),
        migrations.AddIndex(
            model_name="sportsteamweekmetric",
            index=models.Index(fields=["team", "week_of"], name="sports_way_team_week"),
        ),
    ]
