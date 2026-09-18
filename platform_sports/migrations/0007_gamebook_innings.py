from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("platform_sports", "0006_softball_rules_and_game_hr"),
    ]

    operations = [
        migrations.CreateModel(
            name="SportsGameInning",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("inning", models.PositiveSmallIntegerField()),
                ("team_runs", models.PositiveSmallIntegerField(default=0)),
                ("opponent_runs", models.PositiveSmallIntegerField(default=0)),
                ("opponent_hits", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("game", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="inning_lines", to="platform_sports.sportsgame")),
            ],
            options={"ordering": ("inning", "id")},
        ),
        migrations.AddConstraint(
            model_name="sportsgameinning",
            constraint=models.UniqueConstraint(fields=("game", "inning"), name="sports_unique_game_inning"),
        ),
    ]
