from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0017_seed_bed_springs_verified_book_structure"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.AddField(model_name="sportsplayerprofile", name="birth_date", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="sportsplayerprofile", name="show_age", field=models.BooleanField(default=False)),
        migrations.CreateModel(
            name="SportsWeeklyPoll",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("week_start", models.DateField()),
                ("deadline", models.DateTimeField(blank=True, null=True)),
                ("message", models.CharField(blank=True, max_length=300)),
                ("published_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("published_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sports_weekly_polls_created", to=settings.AUTH_USER_MODEL)),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="weekly_polls", to="platform_sports.sportsteam")),
            ],
            options={"ordering": ("week_start", "id")},
        ),
        migrations.AddConstraint(
            model_name="sportsweeklypoll",
            constraint=models.UniqueConstraint(fields=("team", "week_start"), name="sports_unique_weekly_poll"),
        ),
        migrations.CreateModel(
            name="SportsTeamPoll",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("question", models.CharField(max_length=220)),
                ("options", models.JSONField(default=list)),
                ("closes_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("is_closed", models.BooleanField(default=False)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sports_chat_polls_created", to=settings.AUTH_USER_MODEL)),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="chat_polls", to="platform_sports.sportsteam")),
            ],
            options={"ordering": ("-created_at", "-id")},
        ),
        migrations.CreateModel(
            name="SportsTeamPollVote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("option_index", models.PositiveSmallIntegerField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("poll", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="votes", to="platform_sports.sportsteampoll")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sports_team_poll_votes", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="sportsteampollvote",
            constraint=models.UniqueConstraint(fields=("poll", "user"), name="sports_unique_team_poll_vote"),
        ),
        migrations.CreateModel(
            name="SportsCoachAward",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("GOLD_GLOVE", "Golden Glove"), ("HUSTLE", "Hustle Award"), ("TEAM_FIRST", "Team-First Award"), ("PLAYER_WEEK", "Player of the Week"), ("ROOKIE_YEAR", "Rookie of the Year"), ("MOST_IMPROVED", "Most Improved"), ("CUSTOM", "Custom Coach Award")], max_length=24)),
                ("title", models.CharField(blank=True, max_length=100)),
                ("reason", models.CharField(max_length=500)),
                ("season_name", models.CharField(max_length=120)),
                ("award_date", models.DateField(default=django.utils.timezone.localdate)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("awarded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sports_awards_issued", to=settings.AUTH_USER_MODEL)),
                ("game", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="coach_awards", to="platform_sports.sportsgame")),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="coach_awards", to="platform_sports.sportsplayer")),
                ("revoked_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sports_awards_revoked", to=settings.AUTH_USER_MODEL)),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="coach_awards", to="platform_sports.sportsteam")),
            ],
            options={"ordering": ("-award_date", "-id")},
        ),
        migrations.AddConstraint(
            model_name="sportscoachaward",
            constraint=models.UniqueConstraint(fields=("team", "season_name"), condition=models.Q(kind="ROOKIE_YEAR", revoked_at__isnull=True), name="sports_unique_active_rookie_award"),
        ),
        migrations.AddConstraint(
            model_name="sportscoachaward",
            constraint=models.UniqueConstraint(fields=("team", "kind", "award_date"), condition=models.Q(kind="PLAYER_WEEK", revoked_at__isnull=True), name="sports_unique_weekly_player_award"),
        ),
    ]
