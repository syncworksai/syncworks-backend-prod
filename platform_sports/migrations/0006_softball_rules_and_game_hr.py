from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("platform_sports", "0005_correct_bed_springs_dues"),
    ]

    operations = [
        migrations.CreateModel(
            name="SoftballRuleSet",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=140)),
                ("competition_type", models.CharField(choices=[("LEAGUE", "League"), ("TOURNAMENT", "Tournament"), ("OTHER", "Other")], default="LEAGUE", max_length=12)),
                ("innings", models.PositiveSmallIntegerField(default=7)),
                ("home_run_rule", models.CharField(choices=[("UNLIMITED", "Unlimited"), ("FIXED", "Fixed cap"), ("ONE_UP", "One-up / San Diego")], default="UNLIMITED", max_length=12)),
                ("home_run_limit", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("home_run_max_ahead", models.PositiveSmallIntegerField(default=1)),
                ("notes", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="softball_rule_sets_created", to=settings.AUTH_USER_MODEL)),
                ("division", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="softball_rule_sets", to="platform_sports.leaguedivision")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="softball_rule_sets", to="platform_sports.sportsorganization")),
                ("season", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="softball_rule_sets", to="platform_sports.leagueseason")),
            ],
            options={
                "ordering": ("organization__name", "competition_type", "name", "id"),
            },
        ),
        migrations.AddConstraint(
            model_name="softballruleset",
            constraint=models.UniqueConstraint(fields=("organization", "name"), name="sports_unique_org_ruleset_name"),
        ),
        migrations.AddIndex(
            model_name="softballruleset",
            index=models.Index(fields=["organization", "competition_type", "is_active"], name="sports_ruleset_lookup"),
        ),
        migrations.AddField(
            model_name="sportsgame",
            name="home_runs_against",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="sportsgame",
            name="rule_set",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="games", to="platform_sports.softballruleset"),
        ),
    ]
