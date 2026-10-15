from django.db import migrations, models


BATTING = {
    "Jacob Lord": (8, 19, 30),
    "Ethan Headley": (6, 13, 22),
    "Marcus Hardy": (8, 20, 29),
    "James Wynn": (5, 15, 21),
    "Jeff Davis": (8, 19, 28),
    "Elijah Headley": (8, 19, 26),
    "Jordan Bray": (6, 15, 21),
    "Shaw Aplin": (8, 10, 24),
    "Zack Azar": (8, 13, 23),
    "Josh Hudson": (8, 9, 22),
    "Russ Browning": (8, 9, 21),
    "Josh Davis": (4, 3, 10),
    "John Harmon": (2, 3, 6),
    "Ronnie Wideman": (4, 5, 14),
    "Scott Rayburn": (2, 2, 6),
}

EXECUTION_OPPORTUNITIES = {
    "Jacob Lord": 27,
    "Ronnie Wideman": 7,
    "Ethan Headley": 25,
    "Marcus Hardy": 23,
    "James Wynn": 20,
    "Jeff Davis": 24,
    "Elijah Headley": 18,
    "Jordan Bray": 15,
    "Shaw Aplin": 18,
    "Zack Azar": 18,
    "John Harmon": 6,
    "Josh Davis": 5,
    "Josh Hudson": 17,
    "Russ Browning": 17,
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
    SportsPlayerSituationalSplit = apps.get_model("platform_sports", "SportsPlayerSituationalSplit")
    SportsPlayerExecutionTotal = apps.get_model("platform_sports", "SportsPlayerExecutionTotal")

    team = _target_team(apps)
    if not team:
        return
    season_name = team.season_name or "Fall 2026"

    for display_name, (games, hits, at_bats) in BATTING.items():
        player = SportsPlayer.objects.filter(
            team_id=team.id,
            display_name__iexact=display_name,
            is_active=True,
            merged_into_id__isnull=True,
        ).first()
        if not player:
            continue
        split = SportsPlayerSituationalSplit.objects.filter(
            team_id=team.id,
            player_id=player.id,
            season_name=season_name,
        ).first()
        if split:
            split.batting_sample_games = games
            split.batting_hits = hits
            split.batting_ab = at_bats
            split.save(update_fields=("batting_sample_games", "batting_hits", "batting_ab"))

    for display_name, opportunities in EXECUTION_OPPORTUNITIES.items():
        player = SportsPlayer.objects.filter(
            team_id=team.id,
            display_name__iexact=display_name,
            is_active=True,
            merged_into_id__isnull=True,
        ).first()
        if not player:
            continue
        SportsPlayerExecutionTotal.objects.filter(
            team_id=team.id,
            player_id=player.id,
            season_name=season_name,
        ).update(opportunities=opportunities)


def reverse_snapshot(apps, schema_editor):
    SportsPlayerSituationalSplit = apps.get_model("platform_sports", "SportsPlayerSituationalSplit")
    SportsPlayerExecutionTotal = apps.get_model("platform_sports", "SportsPlayerExecutionTotal")
    team = _target_team(apps)
    if not team:
        return
    SportsPlayerSituationalSplit.objects.filter(team_id=team.id).update(
        batting_sample_games=0,
        batting_hits=0,
        batting_ab=0,
    )
    SportsPlayerExecutionTotal.objects.filter(team_id=team.id).update(opportunities=0)


class Migration(migrations.Migration):
    dependencies = [("platform_sports", "0033_correct_jordan_two_out_ab")]

    operations = [
        migrations.AddField(
            model_name="sportsplayerexecutiontotal",
            name="opportunities",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="sportsplayersituationalsplit",
            name="batting_ab",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="sportsplayersituationalsplit",
            name="batting_hits",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="sportsplayersituationalsplit",
            name="batting_sample_games",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.RunPython(seed_snapshot, reverse_snapshot),
    ]
