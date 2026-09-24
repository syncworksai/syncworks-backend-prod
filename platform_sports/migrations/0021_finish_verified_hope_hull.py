"""Mark the already-recorded Hope Hull 20–12 game final.

The score and five inning totals were recorded from the paper sheet in
September's initial Game Book migration, but its state was left LIVE.
Do not invent or modify individual batting events here.
"""
from django.db import migrations


def finish_confirmed_hope_hull(apps, schema_editor):
    Game = apps.get_model("platform_sports", "SportsGame")
    Inning = apps.get_model("platform_sports", "SportsGameInning")
    matches = list(Game.objects.filter(
        team__group__name="Bed Springs Baptist",
        team__sport="SOFTBALL",
        opponent_name="Hope Hull Church",
        status="LIVE",
        runs_for=20,
        runs_against=12,
        start_at__year=2026,
        start_at__month=9,
    )[:2])
    if len(matches) != 1:
        return
    game = matches[0]
    inning_totals = list(Inning.objects.filter(game_id=game.pk).order_by("inning").values_list("inning", "team_runs"))
    if inning_totals != [(1, 6), (2, 3), (3, 3), (4, 5), (5, 3)]:
        return
    Game.objects.filter(pk=game.pk, status="LIVE", runs_for=20, runs_against=12).update(status="FINAL")


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0020_practice_mode_and_live_situations"),
    ]

    operations = [
        migrations.RunPython(finish_confirmed_hope_hull, migrations.RunPython.noop),
    ]
