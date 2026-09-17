from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("platform_sports", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SportsOrganization",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=180)),
                ("slug", models.SlugField(max_length=190, unique=True)),
                ("kind", models.CharField(choices=[("LEAGUE", "League"), ("SANCTION", "Sanction / association"), ("CLUB_NETWORK", "Club network"), ("OTHER", "Other")], default="LEAGUE", max_length=20)),
                ("sport", models.CharField(choices=[("SOFTBALL", "Softball"), ("BASEBALL", "Baseball"), ("BASKETBALL", "Basketball"), ("SOCCER", "Soccer"), ("FOOTBALL", "Football"), ("VOLLEYBALL", "Volleyball"), ("OTHER", "Other")], default="SOFTBALL", max_length=20)),
                ("city", models.CharField(blank=True, max_length=100)),
                ("state", models.CharField(blank=True, max_length=80)),
                ("description", models.TextField(blank=True)),
                ("is_public", models.BooleanField(default=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sports_organizations_created", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("name", "id")},
        ),
        migrations.CreateModel(
            name="SportsPlayerIdentity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(max_length=254, unique=True)),
                ("display_name", models.CharField(blank=True, max_length=180)),
                ("claim_token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("claimed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sports_identity", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("display_name", "email", "id")},
        ),
        migrations.CreateModel(
            name="SportsOrganizationMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("COMMISSIONER", "Commissioner"), ("ADMIN", "Admin"), ("STAFF", "Staff")], default="STAFF", max_length=20)),
                ("status", models.CharField(choices=[("INVITED", "Invited"), ("ACTIVE", "Active"), ("REMOVED", "Removed")], default="ACTIVE", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("invited_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sports_organization_invites_sent", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="memberships", to="platform_sports.sportsorganization")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sports_organization_memberships", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="LeagueSeason",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=140)),
                ("starts_on", models.DateField(blank=True, null=True)),
                ("ends_on", models.DateField(blank=True, null=True)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("ACTIVE", "Active"), ("COMPLETE", "Complete"), ("ARCHIVED", "Archived")], default="DRAFT", max_length=12)),
                ("is_current", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sports_seasons_created", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="seasons", to="platform_sports.sportsorganization")),
            ],
            options={"ordering": ("-is_current", "-starts_on", "name", "id")},
        ),
        migrations.CreateModel(
            name="LeagueDivision",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=140)),
                ("code", models.CharField(blank=True, max_length=40)),
                ("description", models.TextField(blank=True)),
                ("max_roster_size", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("season", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="divisions", to="platform_sports.leagueseason")),
            ],
            options={"ordering": ("name", "id")},
        ),
        migrations.CreateModel(
            name="LeagueTeamEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("ACTIVE", "Active"), ("REMOVED", "Removed")], default="ACTIVE", max_length=12)),
                ("seed", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("division", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="team_entries", to="platform_sports.leaguedivision")),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="league_entries", to="platform_sports.sportsteam")),
            ],
            options={"ordering": ("seed", "team__group__name", "id")},
        ),
        migrations.CreateModel(
            name="LeagueRosterEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("jersey_number", models.CharField(blank=True, max_length=12)),
                ("status", models.CharField(choices=[("INVITED", "Invited"), ("ACTIVE", "Active"), ("INELIGIBLE", "Ineligible"), ("REMOVED", "Removed")], default="INVITED", max_length=12)),
                ("invited_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                ("notes", models.CharField(blank=True, max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("division", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="roster_entries", to="platform_sports.leaguedivision")),
                ("identity", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="roster_entries", to="platform_sports.sportsplayeridentity")),
                ("invited_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="league_roster_invites_sent", to=settings.AUTH_USER_MODEL)),
                ("sports_player", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="league_roster_entries", to="platform_sports.sportsplayer")),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="league_roster_entries", to="platform_sports.sportsteam")),
            ],
            options={"ordering": ("team__group__name", "identity__display_name", "identity__email", "id")},
        ),
        migrations.AddConstraint(
            model_name="sportsorganizationmembership",
            constraint=models.UniqueConstraint(fields=("organization", "user"), name="sports_unique_org_membership"),
        ),
        migrations.AddConstraint(
            model_name="leagueseason",
            constraint=models.UniqueConstraint(fields=("organization", "name"), name="sports_unique_org_season_name"),
        ),
        migrations.AddConstraint(
            model_name="leaguedivision",
            constraint=models.UniqueConstraint(fields=("season", "name"), name="sports_unique_season_division_name"),
        ),
        migrations.AddConstraint(
            model_name="leagueteamentry",
            constraint=models.UniqueConstraint(fields=("division", "team"), name="sports_unique_division_team"),
        ),
        migrations.AddConstraint(
            model_name="leaguerosterentry",
            constraint=models.UniqueConstraint(fields=("division", "team", "identity"), name="sports_unique_div_team_identity"),
        ),
        migrations.AddIndex(
            model_name="sportsorganization",
            index=models.Index(fields=["sport", "is_active"], name="sports_org_sport_active"),
        ),
        migrations.AddIndex(
            model_name="sportsorganizationmembership",
            index=models.Index(fields=["user", "status"], name="sports_org_member_user"),
        ),
        migrations.AddIndex(
            model_name="leagueteamentry",
            index=models.Index(fields=["division", "status"], name="sports_div_team_status"),
        ),
        migrations.AddIndex(
            model_name="leaguerosterentry",
            index=models.Index(fields=["division", "team", "status"], name="sports_roster_lookup"),
        ),
    ]
