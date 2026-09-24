"""Restore Hope Hull's completed-game status without changing its official score.

The game was accidentally left LIVE after historical score and inning totals
were imported. Only correct the exact Bed Springs game if the final score and
five inning totals still match the original paper book. This migration never
creates unverified batting statistics from handwriting.
"""
from django.db import migrations


def finalize_confirmed_hope_hull(apps, schema_editor):
    Game = apps.get_model("platform_sports", "SportsGame")
    Inning = apps.get_model("platform_sports", "SportsGameInning")
    matches = list(
        Game.objects.filter(
            team__group__name="Bed Springs Baptist",
            opponent_name="Hope Hull Church",
            runs_for=20,
            runs_against=12,
        )[:2]
    )
    if len(matches) != 1:
        return
    game = matches[0]
    expected = {1: 6, 2: 3, 3: 3, 4: 5, 5: 3}
    actual = dict(Inning.objects.filter(game=game).values_list("inning", "team_runs"))
    if actual != expected or game.status != "LIVE":
        return
    game.status = "FINAL"
    game.current_inning = 5
    game.save(update_fields=("status", "current_inning", "updated_at"))


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0020_practice_mode_and_live_situations"),
    ]
    operations = [
        migrations.RunPython(finalize_confirmed_hope_hull, migrations.RunPython.noop),
    ]
