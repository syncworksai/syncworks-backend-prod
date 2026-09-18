from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("platform_sports", "0007_gamebook_innings"),
    ]

    operations = [
        migrations.CreateModel(
            name="LeagueTournament",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=180)),
                ("format", models.CharField(choices=[("SINGLE_ELIM", "Single elimination"), ("ROUND_ROBIN", "Round robin")], default="SINGLE_ELIM", max_length=20)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("ACTIVE", "Active"), ("COMPLETE", "Complete"), ("CANCELLED", "Cancelled")], default="DRAFT", max_length=12)),
                ("starts_on", models.DateField(blank=True, null=True)),
                ("ends_on", models.DateField(blank=True, null=True)),
                ("venue_name", models.CharField(blank=True, max_length=180)),
                ("address_line1", models.CharField(blank=True, max_length=220)),
                ("city", models.CharField(blank=True, max_length=100)),
                ("state", models.CharField(blank=True, max_length=80)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sports_tournaments_created", to=settings.AUTH_USER_MODEL)),
                ("division", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="tournaments", to="platform_sports.leaguedivision")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tournaments", to="platform_sports.sportsorganization")),
                ("rule_set", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="tournaments", to="platform_sports.softballruleset")),
                ("season", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="tournaments", to="platform_sports.leagueseason")),
            ],
            options={"ordering": ("-starts_on", "name", "id")},
        ),
        migrations.AddConstraint(model_name="leaguetournament", constraint=models.UniqueConstraint(fields=("organization", "name"), name="sports_unique_org_tournament_name")),
        migrations.CreateModel(
            name="LeagueTournamentEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("seed", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tournament_entries", to="platform_sports.sportsteam")),
                ("tournament", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="entries", to="platform_sports.leaguetournament")),
            ],
            options={"ordering": ("seed", "team__group__name", "id")},
        ),
        migrations.AddConstraint(model_name="leaguetournamententry", constraint=models.UniqueConstraint(fields=("tournament", "team"), name="sports_unique_tournament_team")),
        migrations.CreateModel(
            name="LeagueTournamentBye",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("round_number", models.PositiveSmallIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tournament_byes", to="platform_sports.sportsteam")),
                ("tournament", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="byes", to="platform_sports.leaguetournament")),
            ],
            options={"ordering": ("round_number", "team__group__name", "id")},
        ),
        migrations.AddConstraint(model_name="leaguetournamentbye", constraint=models.UniqueConstraint(fields=("tournament", "round_number", "team"), name="sports_unique_tournament_round_bye")),
        migrations.CreateModel(
            name="LeagueGame",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(choices=[("LEAGUE", "League"), ("TOURNAMENT", "Tournament")], default="LEAGUE", max_length=12)),
                ("start_at", models.DateTimeField()),
                ("end_at", models.DateTimeField(blank=True, null=True)),
                ("timezone", models.CharField(default="America/Chicago", max_length=64)),
                ("venue_name", models.CharField(blank=True, max_length=180)),
                ("field_name", models.CharField(blank=True, max_length=100)),
                ("address_line1", models.CharField(blank=True, max_length=220)),
                ("city", models.CharField(blank=True, max_length=100)),
                ("state", models.CharField(blank=True, max_length=80)),
                ("week_number", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("round_number", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("bracket_slot", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("status", models.CharField(choices=[("SCHEDULED", "Scheduled"), ("LIVE", "Live"), ("FINAL", "Final"), ("CANCELLED", "Cancelled")], default="SCHEDULED", max_length=12)),
                ("home_score", models.PositiveSmallIntegerField(default=0)),
                ("away_score", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("away_sports_game", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="league_away_record", to="platform_sports.sportsgame")),
                ("away_team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="league_away_games", to="platform_sports.sportsteam")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="league_games_created", to=settings.AUTH_USER_MODEL)),
                ("division", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="league_games", to="platform_sports.leaguedivision")),
                ("home_sports_game", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="league_home_record", to="platform_sports.sportsgame")),
                ("home_team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="league_home_games", to="platform_sports.sportsteam")),
                ("rule_set", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="league_games", to="platform_sports.softballruleset")),
                ("tournament", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="games", to="platform_sports.leaguetournament")),
            ],
            options={
                "ordering": ("start_at", "id"),
                "indexes": [
                    models.Index(fields=["division", "status", "start_at"], name="sports_league_game_lookup"),
                    models.Index(fields=["tournament", "round_number"], name="sports_tournament_round"),
                ],
            },
        ),
    ]
