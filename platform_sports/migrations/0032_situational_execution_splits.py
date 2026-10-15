from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


SPLITS = {
    "Jacob Lord": (8, 11, 4, 7, 6, 7),
    "Ethan Headley": (2, 3, 3, 3, 6, 8),
    "Marcus Hardy": (2, 2, 3, 4, 12, 16),
    "James Wynn": (3, 3, 2, 2, 6, 7),
    "Jeff Davis": (2, 2, 3, 4, 12, 16),
    "Elijah Headley": (4, 5, 4, 7, 9, 11),
    "Jordan Bray": (0, 0, 2, 2, 7, 9),
    "Shaw Aplin": (0, 2, 3, 7, 4, 10),
    "Zack Azar": (3, 7, 1, 2, 5, 7),
    "Josh Hudson": (2, 3, 3, 4, 4, 10),
    "Russ Browning": (1, 2, 3, 4, 7, 9),
    "Josh Davis": (1, 2, 0, 0, 1, 3),
    "John Harmon": (1, 1, 1, 1, 3, 4),
    "Ronnie Wideman": (2, 2, 0, 0, 1, 4),
    "Scott Rayburn": (0, 1, 0, 1, 1, 3),
}


SEED_NOTE = "Six-game situational split entered by coach 2026-10-14; first two season games excluded because situation data was not kept reliably."


def seed_situational_splits(apps, schema_editor):
    SocialGroup = apps.get_model("platform_social", "SocialGroup")
    SportsTeam = apps.get_model("platform_sports", "SportsTeam")
    SportsPlayer = apps.get_model("platform_sports", "SportsPlayer")
    SportsPlayerSituationalSplit = apps.get_model("platform_sports", "SportsPlayerSituationalSplit")

    group = SocialGroup.objects.filter(name__iexact="Bed Springs Baptist").first()
    if not group:
        return
    team = SportsTeam.objects.filter(group_id=group.id).first()
    if not team:
        return
    season_name = team.season_name or "Fall 2026"

    for display_name, values in SPLITS.items():
        player = SportsPlayer.objects.filter(
            team_id=team.id,
            display_name__iexact=display_name,
            is_active=True,
            merged_into_id__isnull=True,
        ).first()
        if not player:
            continue
        empty_h, empty_ab, two_h, two_ab, rob_h, rob_ab = values
        SportsPlayerSituationalSplit.objects.update_or_create(
            team_id=team.id,
            player_id=player.id,
            season_name=season_name,
            defaults={
                "sample_games": 6,
                "bases_empty_hits": empty_h,
                "bases_empty_ab": empty_ab,
                "two_out_hits": two_h,
                "two_out_ab": two_ab,
                "runners_on_hits": rob_h,
                "runners_on_ab": rob_ab,
                "note": SEED_NOTE,
            },
        )


def unseed_situational_splits(apps, schema_editor):
    SportsPlayerSituationalSplit = apps.get_model("platform_sports", "SportsPlayerSituationalSplit")
    SportsPlayerSituationalSplit.objects.filter(note=SEED_NOTE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0031_qab_totals"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SportsPlayerSituationalSplit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("season_name", models.CharField(blank=True, max_length=80)),
                ("sample_games", models.PositiveSmallIntegerField(default=0)),
                ("bases_empty_hits", models.PositiveIntegerField(default=0)),
                ("bases_empty_ab", models.PositiveIntegerField(default=0)),
                ("two_out_hits", models.PositiveIntegerField(default=0)),
                ("two_out_ab", models.PositiveIntegerField(default=0)),
                ("runners_on_hits", models.PositiveIntegerField(default=0)),
                ("runners_on_ab", models.PositiveIntegerField(default=0)),
                ("note", models.CharField(blank=True, max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="way_situational_splits", to="platform_sports.sportsplayer")),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="way_situational_splits", to="platform_sports.sportsteam")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sports_situational_splits_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("player__display_name", "id")},
        ),
        migrations.AddConstraint(
            model_name="sportsplayersituationalsplit",
            constraint=models.UniqueConstraint(fields=("team", "player", "season_name"), name="sports_unique_situational_split_season"),
        ),
        migrations.AddIndex(
            model_name="sportsplayersituationalsplit",
            index=models.Index(fields=["team", "season_name"], name="sports_situational_season"),
        ),
        migrations.RunPython(seed_situational_splits, unseed_situational_splits),
    ]
