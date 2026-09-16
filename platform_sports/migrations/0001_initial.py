from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("platform_social", "0002_socialevent_recurrence_weather"),
    ]

    operations = [
        migrations.CreateModel(
            name="SportsTeam",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sport", models.CharField(choices=[("SOFTBALL", "Softball"), ("BASEBALL", "Baseball"), ("BASKETBALL", "Basketball"), ("SOCCER", "Soccer"), ("FOOTBALL", "Football"), ("VOLLEYBALL", "Volleyball"), ("OTHER", "Other")], default="SOFTBALL", max_length=20)),
                ("season_name", models.CharField(blank=True, max_length=120)),
                ("league_name", models.CharField(blank=True, max_length=180)),
                ("division_name", models.CharField(blank=True, max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sports_teams_created", to=settings.AUTH_USER_MODEL)),
                ("group", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="sports_team", to="platform_social.socialgroup")),
            ],
            options={"ordering": ("group__name", "id")},
        ),
        migrations.CreateModel(
            name="SportsPlayer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_name", models.CharField(max_length=180)),
                ("jersey_number", models.CharField(blank=True, max_length=12)),
                ("bats", models.CharField(blank=True, choices=[("L", "Left"), ("R", "Right"), ("S", "Switch"), ("", "Not set")], default="", max_length=1)),
                ("throws", models.CharField(blank=True, choices=[("L", "Left"), ("R", "Right"), ("S", "Switch"), ("", "Not set")], default="", max_length=1)),
                ("primary_position", models.CharField(blank=True, max_length=40)),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sports_players_created", to=settings.AUTH_USER_MODEL)),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="players", to="platform_sports.sportsteam")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sports_player_profiles", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("sort_order", "display_name", "id")},
        ),
        migrations.CreateModel(
            name="SportsGame",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("game_type", models.CharField(choices=[("LEAGUE", "League"), ("TOURNAMENT", "Tournament"), ("PRACTICE", "Practice"), ("EXHIBITION", "Exhibition")], default="LEAGUE", max_length=16)),
                ("opponent_name", models.CharField(max_length=180)),
                ("tournament_name", models.CharField(blank=True, max_length=180)),
                ("round_label", models.CharField(blank=True, max_length=120)),
                ("home_away", models.CharField(choices=[("HOME", "Home"), ("AWAY", "Away"), ("NEUTRAL", "Neutral")], default="NEUTRAL", max_length=10)),
                ("start_at", models.DateTimeField()),
                ("end_at", models.DateTimeField(blank=True, null=True)),
                ("timezone", models.CharField(default="America/Chicago", max_length=64)),
                ("venue_name", models.CharField(blank=True, max_length=180)),
                ("address_line1", models.CharField(blank=True, max_length=220)),
                ("city", models.CharField(blank=True, max_length=100)),
                ("state", models.CharField(blank=True, max_length=80)),
                ("notes", models.TextField(blank=True)),
                ("innings_scheduled", models.PositiveSmallIntegerField(default=7)),
                ("status", models.CharField(choices=[("SCHEDULED", "Scheduled"), ("LIVE", "Live"), ("FINAL", "Final"), ("CANCELLED", "Cancelled")], default="SCHEDULED", max_length=12)),
                ("current_inning", models.PositiveSmallIntegerField(default=1)),
                ("outs", models.PositiveSmallIntegerField(default=0)),
                ("current_batter_order", models.PositiveSmallIntegerField(default=1)),
                ("runs_for", models.PositiveSmallIntegerField(default=0)),
                ("runs_against", models.PositiveSmallIntegerField(default=0)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sports_games_created", to=settings.AUTH_USER_MODEL)),
                ("social_event", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sports_game", to="platform_social.socialevent")),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="games", to="platform_sports.sportsteam")),
            ],
            options={"ordering": ("start_at", "id")},
        ),
        migrations.CreateModel(
            name="SportsLineupSpot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("batting_order", models.PositiveSmallIntegerField()),
                ("defensive_position", models.CharField(blank=True, max_length=40)),
                ("is_starter", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("game", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lineup_spots", to="platform_sports.sportsgame")),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lineup_spots", to="platform_sports.sportsplayer")),
            ],
            options={"ordering": ("batting_order", "id")},
        ),
        migrations.CreateModel(
            name="SoftballPlateAppearance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sequence", models.PositiveIntegerField()),
                ("inning", models.PositiveSmallIntegerField(default=1)),
                ("result", models.CharField(choices=[("1B", "Single"), ("2B", "Double"), ("3B", "Triple"), ("HR", "Home run"), ("BB", "Walk"), ("OUT", "Out"), ("K", "Strikeout"), ("ROE", "Reached on error"), ("FC", "Fielder's choice"), ("SF", "Sacrifice fly")], max_length=4)),
                ("outs_recorded", models.PositiveSmallIntegerField(default=0)),
                ("rbi", models.PositiveSmallIntegerField(default=0)),
                ("runs_scored", models.PositiveSmallIntegerField(default=0)),
                ("notes", models.CharField(blank=True, max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="softball_plate_appearances_created", to=settings.AUTH_USER_MODEL)),
                ("game", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="plate_appearances", to="platform_sports.sportsgame")),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="plate_appearances", to="platform_sports.sportsplayer")),
            ],
            options={"ordering": ("sequence", "id")},
        ),
        migrations.AddConstraint(
            model_name="sportsplayer",
            constraint=models.UniqueConstraint(condition=models.Q(("user__isnull", False)), fields=("team", "user"), name="sports_unique_team_user"),
        ),
        migrations.AddIndex(
            model_name="sportsplayer",
            index=models.Index(fields=["team", "is_active"], name="sports_player_active"),
        ),
        migrations.AddIndex(
            model_name="sportsgame",
            index=models.Index(fields=["team", "status", "start_at"], name="sports_game_lookup"),
        ),
        migrations.AddConstraint(
            model_name="sportslineupspot",
            constraint=models.UniqueConstraint(fields=("game", "batting_order"), name="sports_unique_bat_order"),
        ),
        migrations.AddConstraint(
            model_name="sportslineupspot",
            constraint=models.UniqueConstraint(fields=("game", "player"), name="sports_unique_game_player"),
        ),
        migrations.AddConstraint(
            model_name="softballplateappearance",
            constraint=models.UniqueConstraint(fields=("game", "sequence"), name="sports_unique_pa_sequence"),
        ),
        migrations.AddIndex(
            model_name="softballplateappearance",
            index=models.Index(fields=["game", "player"], name="sports_pa_game_player"),
        ),
    ]
