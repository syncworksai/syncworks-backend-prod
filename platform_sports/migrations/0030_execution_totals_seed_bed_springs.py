from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


EXECUTION_POINTS = {
    "Jacob Lord": Decimal("15"),
    "Ronnie Wideman": Decimal("3"),
    "Ethan Headley": Decimal("10"),
    "Marcus Hardy": Decimal("16.5"),
    "James Wynn": Decimal("10"),
    "Jeff Davis": Decimal("11"),
    "Elijah Headley": Decimal("16"),
    "Jordan Bray": Decimal("10"),
    "Shaw Aplin": Decimal("10"),
    "Zack Azar": Decimal("10"),
    "John Harmon": Decimal("4"),
    "Josh Davis": Decimal("1"),
    "Josh Hudson": Decimal("8"),
    "Russ Browning": Decimal("9"),
}


def seed_bed_springs_execution(apps, schema_editor):
    SocialGroup = apps.get_model("platform_social", "SocialGroup")
    SportsTeam = apps.get_model("platform_sports", "SportsTeam")
    SportsPlayer = apps.get_model("platform_sports", "SportsPlayer")
    SportsPlayerExecutionTotal = apps.get_model("platform_sports", "SportsPlayerExecutionTotal")

    group = SocialGroup.objects.filter(name__iexact="Bed Springs Baptist").first()
    if not group:
        return
    team = SportsTeam.objects.filter(group_id=group.id).first()
    if not team:
        return
    season_name = team.season_name or "Fall 2026"

    for display_name, points in EXECUTION_POINTS.items():
        player = SportsPlayer.objects.filter(
            team_id=team.id,
            display_name__iexact=display_name,
            is_active=True,
            merged_into_id__isnull=True,
        ).first()
        if not player:
            continue
        SportsPlayerExecutionTotal.objects.update_or_create(
            team_id=team.id,
            player_id=player.id,
            season_name=season_name,
            defaults={
                "points": points,
                "note": "Initial all-games execution points entered by coach 2026-10-14",
            },
        )


def unseed_bed_springs_execution(apps, schema_editor):
    SocialGroup = apps.get_model("platform_social", "SocialGroup")
    SportsTeam = apps.get_model("platform_sports", "SportsTeam")
    SportsPlayerExecutionTotal = apps.get_model("platform_sports", "SportsPlayerExecutionTotal")

    group = SocialGroup.objects.filter(name__iexact="Bed Springs Baptist").first()
    if not group:
        return
    team = SportsTeam.objects.filter(group_id=group.id).first()
    if not team:
        return
    SportsPlayerExecutionTotal.objects.filter(
        team_id=team.id,
        note="Initial all-games execution points entered by coach 2026-10-14",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0029_way_metrics_and_weekly_targets"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SportsPlayerExecutionTotal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("season_name", models.CharField(blank=True, max_length=80)),
                ("points", models.DecimalField(decimal_places=2, default=0, max_digits=8)),
                ("note", models.CharField(blank=True, max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="way_execution_totals", to="platform_sports.sportsplayer")),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="way_execution_totals", to="platform_sports.sportsteam")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sports_execution_totals_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("player__display_name", "id")},
        ),
        migrations.AddConstraint(
            model_name="sportsplayerexecutiontotal",
            constraint=models.UniqueConstraint(fields=("team", "player", "season_name"), name="sports_unique_execution_total_season"),
        ),
        migrations.AddIndex(
            model_name="sportsplayerexecutiontotal",
            index=models.Index(fields=["team", "season_name"], name="sports_exec_total_season"),
        ),
        migrations.RunPython(seed_bed_springs_execution, unseed_bed_springs_execution),
    ]
