from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0017_seed_bed_springs_verified_book_structure"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="sportsplayerprofile",
            name="date_of_birth",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="sportsplayerprofile",
            name="show_age_to_team",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="SportsPlayerAward",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[
                    ("PLAYER_OF_WEEK", "Player of the Week"),
                    ("ROOKIE_OF_YEAR", "Rookie of the Year"),
                    ("GOLD_GLOVE", "Gold Glove"),
                    ("HUSTLE", "Hustle Award"),
                    ("TEAM_FIRST", "Team First"),
                    ("MVP", "Most Valuable Player"),
                    ("CUSTOM", "Custom"),
                ], default="CUSTOM", max_length=24)),
                ("title", models.CharField(max_length=120)),
                ("season_name", models.CharField(blank=True, max_length=120)),
                ("week_of", models.DateField(blank=True, null=True)),
                ("note", models.CharField(blank=True, max_length=500)),
                ("awarded_at", models.DateTimeField(auto_now_add=True)),
                ("awarded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sports_awards_given", to=settings.AUTH_USER_MODEL)),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="coach_awards", to="platform_sports.sportsplayer")),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="player_awards", to="platform_sports.sportsteam")),
            ],
            options={"ordering": ("-awarded_at", "-id")},
        ),
        migrations.AddIndex(
            model_name="sportsplayeraward",
            index=models.Index(fields=["team", "season_name"], name="sports_award_team_season"),
        ),
        migrations.AddIndex(
            model_name="sportsplayeraward",
            index=models.Index(fields=["player", "kind"], name="sports_award_player_kind"),
        ),
        migrations.AddConstraint(
            model_name="sportsplayeraward",
            constraint=models.UniqueConstraint(fields=("team", "player", "kind", "season_name", "week_of"), name="sports_unique_player_award_period"),
        ),
    ]
