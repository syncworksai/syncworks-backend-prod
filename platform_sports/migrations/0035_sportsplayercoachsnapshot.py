from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("platform_sports", "0034_eight_game_batting_snapshot_and_execution_opportunities"),
    ]

    operations = [
        migrations.CreateModel(
            name="SportsPlayerCoachSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("week_of", models.DateField()),
                ("recommended_role", models.CharField(blank=True, max_length=96)),
                ("recommended_slots", models.CharField(blank=True, max_length=24)),
                ("role_reason", models.CharField(blank=True, max_length=320)),
                ("focus_key", models.CharField(blank=True, max_length=32)),
                ("coaching_action", models.CharField(blank=True, max_length=640)),
                ("projected_runs_per_game_low", models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ("projected_runs_per_game_high", models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ("metrics", models.JSONField(blank=True, default=dict)),
                ("role_override", models.CharField(blank=True, max_length=96)),
                ("slots_override", models.CharField(blank=True, max_length=24)),
                ("focus_override", models.CharField(blank=True, max_length=32)),
                ("coach_note", models.CharField(blank=True, max_length=640)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="coach_snapshots", to="platform_sports.sportsplayer")),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="coach_snapshots", to="platform_sports.sportsteam")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sports_coach_snapshots_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-week_of", "player__display_name", "id")},
        ),
        migrations.AddConstraint(
            model_name="sportsplayercoachsnapshot",
            constraint=models.UniqueConstraint(fields=("team", "player", "week_of"), name="sports_unique_coach_snapshot_week"),
        ),
        migrations.AddIndex(
            model_name="sportsplayercoachsnapshot",
            index=models.Index(fields=["team", "week_of"], name="sports_coach_snapshot_week"),
        ),
        migrations.AddIndex(
            model_name="sportsplayercoachsnapshot",
            index=models.Index(fields=["player", "week_of"], name="sports_coach_snapshot_player"),
        ),
    ]
