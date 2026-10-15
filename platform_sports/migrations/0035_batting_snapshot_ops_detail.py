from django.db import migrations, models


SNAPSHOT = {
    "Jacob Lord": (8, 19, 30, 7, 0, 0, 6, 0),
    "Ethan Headley": (6, 13, 22, 1, 0, 0, 3, 0),
    "Marcus Hardy": (8, 20, 29, 2, 0, 6, 3, 0),
    "James Wynn": (5, 15, 21, 2, 0, 0, 0, 0),
    "Jeff Davis": (8, 19, 28, 2, 2, 1, 3, 3),
    "Elijah Headley": (8, 19, 26, 3, 0, 0, 2, 4),
    "Jordan Bray": (6, 14, 21, 2, 0, 0, 2, 0),
    "Shaw Aplin": (8, 10, 24, 0, 0, 0, 1, 0),
    "Zack Azar": (8, 13, 23, 2, 2, 0, 0, 0),
    "Josh Hudson": (8, 9, 22, 1, 0, 0, 2, 0),
    "Russ Browning": (8, 9, 21, 0, 0, 0, 3, 0),
    "Josh Davis": (4, 3, 10, 0, 0, 0, 1, 0),
    "John Harmon": (2, 3, 6, 0, 0, 0, 0, 0),
    "Ronnie Wideman": (4, 5, 14, 0, 0, 0, 2, 0),
    "Scott Rayburn": (2, 2, 6, 0, 0, 0, 1, 0),
}


def _target_team(apps):
    SocialGroup = apps.get_model("platform_social", "SocialGroup")
    SportsTeam = apps.get_model("platform_sports", "SportsTeam")
    group = SocialGroup.objects.filter(name__iexact="Bed Springs Baptist").first()
    if not group:
        return None
    return SportsTeam.objects.filter(group_id=group.id).first()


def seed_snapshot(apps, schema_editor):
    SportsPlayer = apps.get_model("platform_sports", "SportsPlayer")
    Split = apps.get_model("platform_sports", "SportsPlayerSituationalSplit")
    team = _target_team(apps)
    if not team:
        return
    season_name = team.season_name or "Fall 2026"
    for name, values in SNAPSHOT.items():
        games, hits, ab, doubles, triples, homers, walks, sac_flies = values
        player = SportsPlayer.objects.filter(
            team_id=team.id,
            display_name__iexact=name,
            is_active=True,
            merged_into_id__isnull=True,
        ).first()
        if not player:
            continue
        Split.objects.filter(
            team_id=team.id,
            player_id=player.id,
            season_name=season_name,
        ).update(
            batting_sample_games=games,
            batting_hits=hits,
            batting_ab=ab,
            batting_doubles=doubles,
            batting_triples=triples,
            batting_home_runs=homers,
            batting_walks=walks,
            batting_sac_flies=sac_flies,
            note="Eight-game batting snapshot; newest two games updated for XBH/BB. H is authoritative and singles are derived from H-XBH.",
        )


def reverse_snapshot(apps, schema_editor):
    Split = apps.get_model("platform_sports", "SportsPlayerSituationalSplit")
    team = _target_team(apps)
    if not team:
        return
    Split.objects.filter(team_id=team.id).update(
        batting_doubles=0,
        batting_triples=0,
        batting_home_runs=0,
        batting_walks=0,
        batting_sac_flies=0,
    )
    jordan = Split.objects.filter(team_id=team.id, player__display_name__iexact="Jordan Bray").first()
    if jordan:
        jordan.batting_hits = 15
        jordan.save(update_fields=("batting_hits",))


class Migration(migrations.Migration):
    dependencies = [("platform_sports", "0034_eight_game_batting_snapshot_and_execution_opportunities")]

    operations = [
        migrations.AddField(
            model_name="sportsplayersituationalsplit",
            name="batting_doubles",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="sportsplayersituationalsplit",
            name="batting_home_runs",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="sportsplayersituationalsplit",
            name="batting_sac_flies",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="sportsplayersituationalsplit",
            name="batting_triples",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="sportsplayersituationalsplit",
            name="batting_walks",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(seed_snapshot, reverse_snapshot),
    ]
