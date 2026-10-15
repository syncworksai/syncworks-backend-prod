from django.db import migrations


def correct_jordan_two_out_ab(apps, schema_editor):
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
    player = SportsPlayer.objects.filter(
        team_id=team.id,
        display_name__iexact="Jordan Bray",
        is_active=True,
        merged_into_id__isnull=True,
    ).first()
    if not player:
        return

    season_name = team.season_name or "Fall 2026"
    SportsPlayerSituationalSplit.objects.filter(
        team_id=team.id,
        player_id=player.id,
        season_name=season_name,
    ).update(
        two_out_hits=2,
        two_out_ab=3,
        note="Six-game situational split entered by coach 2026-10-14; Jordan two-out sample corrected to 2-for-3 on 2026-10-15; first two season games excluded because situation data was not kept reliably.",
    )


def reverse_correction(apps, schema_editor):
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
    player = SportsPlayer.objects.filter(team_id=team.id, display_name__iexact="Jordan Bray").first()
    if not player:
        return
    season_name = team.season_name or "Fall 2026"
    SportsPlayerSituationalSplit.objects.filter(
        team_id=team.id,
        player_id=player.id,
        season_name=season_name,
    ).update(two_out_hits=2, two_out_ab=2)


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0032_situational_execution_splits"),
    ]

    operations = [
        migrations.RunPython(correct_jordan_two_out_ab, reverse_correction),
    ]
