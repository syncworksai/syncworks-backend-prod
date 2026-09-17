from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("platform_sports", "0002_league_management"),
    ]

    operations = [
        migrations.CreateModel(
            name="SportsPlayerProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=40)),
                ("profile_photo", models.ImageField(blank=True, null=True, upload_to="sports/player_profiles/%Y/%m/")),
                ("emergency_contact_name", models.CharField(blank=True, max_length=180)),
                ("emergency_contact_phone", models.CharField(blank=True, max_length=40)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("player", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="manager_profile", to="platform_sports.sportsplayer")),
            ],
            options={"ordering": ("player__display_name", "id")},
        ),
        migrations.CreateModel(
            name="TeamPaymentSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cash_app_url", models.URLField(blank=True)),
                ("venmo_url", models.URLField(blank=True)),
                ("stripe_url", models.URLField(blank=True)),
                ("payment_note", models.CharField(blank=True, max_length=240)),
                ("platform_fee_bps", models.PositiveSmallIntegerField(default=100)),
                ("free_mode", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("team", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="payment_settings", to="platform_sports.sportsteam")),
            ],
        ),
        migrations.CreateModel(
            name="TeamFee",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=180)),
                ("description", models.TextField(blank=True)),
                ("amount_cents", models.PositiveIntegerField(default=0)),
                ("due_date", models.DateField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sports_team_fees_created", to=settings.AUTH_USER_MODEL)),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="fees", to="platform_sports.sportsteam")),
            ],
            options={"ordering": ("due_date", "title", "id")},
        ),
        migrations.CreateModel(
            name="SoftballStatLedgerEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("season_name", models.CharField(blank=True, max_length=120)),
                ("scope", models.CharField(choices=[("LEAGUE", "League"), ("TOURNAMENT", "Tournament"), ("OTHER", "Other")], default="LEAGUE", max_length=16)),
                ("games", models.PositiveIntegerField(default=0)),
                ("pa", models.PositiveIntegerField(default=0)),
                ("ab", models.PositiveIntegerField(default=0)),
                ("hits", models.PositiveIntegerField(default=0)),
                ("doubles", models.PositiveIntegerField(default=0)),
                ("triples", models.PositiveIntegerField(default=0)),
                ("home_runs", models.PositiveIntegerField(default=0)),
                ("walks", models.PositiveIntegerField(default=0)),
                ("sac_flies", models.PositiveIntegerField(default=0)),
                ("rbi", models.PositiveIntegerField(default=0)),
                ("runs", models.PositiveIntegerField(default=0)),
                ("source", models.CharField(choices=[("MANUAL", "Manual"), ("IMPORT", "Import"), ("CORRECTION", "Correction")], default="MANUAL", max_length=16)),
                ("note", models.CharField(blank=True, max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="softball_stat_ledger_entries_created", to=settings.AUTH_USER_MODEL)),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="stat_ledger_entries", to="platform_sports.sportsplayer")),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="stat_ledger_entries", to="platform_sports.sportsteam")),
            ],
            options={"ordering": ("player__display_name", "scope", "id")},
        ),
        migrations.CreateModel(
            name="TeamFeeAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount_cents", models.PositiveIntegerField(default=0)),
                ("amount_paid_cents", models.PositiveIntegerField(default=0)),
                ("status", models.CharField(choices=[("DUE", "Due"), ("PARTIAL", "Partial"), ("PAID", "Paid"), ("WAIVED", "Waived")], default="DUE", max_length=12)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("payment_method", models.CharField(blank=True, max_length=40)),
                ("note", models.CharField(blank=True, max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("fee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assignments", to="platform_sports.teamfee")),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="fee_assignments", to="platform_sports.sportsplayer")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sports_fee_assignments_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("fee__due_date", "player__display_name", "id")},
        ),
        migrations.AddIndex(
            model_name="teamfee",
            index=models.Index(fields=["team", "is_active"], name="sports_fee_team_active"),
        ),
        migrations.AddIndex(
            model_name="softballstatledgerentry",
            index=models.Index(fields=["team", "scope"], name="sports_stat_team_scope"),
        ),
        migrations.AddIndex(
            model_name="teamfeeassignment",
            index=models.Index(fields=["player", "status"], name="sports_fee_player_status"),
        ),
        migrations.AddConstraint(
            model_name="teamfeeassignment",
            constraint=models.UniqueConstraint(fields=("fee", "player"), name="sports_unique_fee_player"),
        ),
    ]
