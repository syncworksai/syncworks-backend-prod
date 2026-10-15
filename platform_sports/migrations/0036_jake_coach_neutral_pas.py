from django.db import migrations


NOTE_SUFFIX = " Three coach-neutral two-out PAs excluded from SIT+/EXE denominators 2026-10-15."


def _target_team(apps):
    SocialGroup = apps.get_model("platform_social", "SocialGroup")
    SportsTeam = apps.get_model("platform_sports", "SportsTeam")
    group = SocialGroup.objects.filter(name__iexact="Bed Springs Baptist").first()
    if not group:
        return None
    return SportsTeam.objects.filter(group_id=group.id).first()


def apply_neutral_pas(apps, schema_editor):
    SportsPlayer = apps.get_model("platform_sports", "SportsPlayer")
    SportsPlayerSituationalSplit = apps.get_model("platform_sports", "SportsPlayerSituationalSplit")
    SportsPlayerExecutionTotal = apps.get_model("platform_sports", "SportsPlayerExecutionTotal")

    team = _target_team(apps)
    if not team:
        return
    season_name = team.season_name or "Fall 2026"
    player = SportsPlayer.objects.filter(
        team_id=team.id,
        display_name__iexact="Jacob Lord",
        is_active=True,
        merged_into_id__isnull=True,
    ).first()
    if not player:
        return

    split = SportsPlayerSituationalSplit.objects.filter(
        team_id=team.id,
        player_id=player.id,
        season_name=season_name,
    ).first()
    if split:
        # Official batting totals remain unchanged. These are only the competitive
        # situational opportunities used by SIT+.
        split.two_out_hits = 4
        split.two_out_ab = 4
        note = split.note or ""
        if NOTE_SUFFIX.strip() not in note:
            split.note = (note + NOTE_SUFFIX)[:240]
        split.save(update_fields=("two_out_hits", "two_out_ab", "note"))

    execution = SportsPlayerExecutionTotal.objects.filter(
        team_id=team.id,
        player_id=player.id,
        season_name=season_name,
    ).first()
    if execution:
        # The three coach-neutral PAs were zero-point graded opportunities, so the
        # numerator stays 15 while the graded denominator moves from 27 to 24.
        execution.opportunities = 24
        note = execution.note or ""
        if NOTE_SUFFIX.strip() not in note:
            execution.note = (note + NOTE_SUFFIX)[:240]
        execution.save(update_fields=("opportunities", "note"))


def reverse_neutral_pas(apps, schema_editor):
    SportsPlayer = apps.get_model("platform_sports", "SportsPlayer")
    SportsPlayerSituationalSplit = apps.get_model("platform_sports", "SportsPlayerSituationalSplit")
    SportsPlayerExecutionTotal = apps.get_model("platform_sports", "SportsPlayerExecutionTotal")

    team = _target_team(apps)
    if not team:
        return
    season_name = team.season_name or "Fall 2026"
    player = SportsPlayer.objects.filter(
        team_id=team.id,
        display_name__iexact="Jacob Lord",
        is_active=True,
        merged_into_id__isnull=True,
    ).first()
    if not player:
        return

    SportsPlayerSituationalSplit.objects.filter(
        team_id=team.id,
        player_id=player.id,
        season_name=season_name,
    ).update(two_out_hits=4, two_out_ab=7)
    SportsPlayerExecutionTotal.objects.filter(
        team_id=team.id,
        player_id=player.id,
        season_name=season_name,
    ).update(opportunities=27)


class Migration(migrations.Migration):
    dependencies = [("platform_sports", "0035_sportsplayercoachsnapshot")]

    operations = [migrations.RunPython(apply_neutral_pas, reverse_neutral_pas)]
