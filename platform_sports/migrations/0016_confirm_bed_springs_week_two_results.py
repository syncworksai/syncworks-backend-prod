"""Finalize only the two confirmed Sept 22 Bed Springs results on existing fixtures.

Never manufacture players, photo-derived hits or additional game rows here.
Historical game stats are imported separately after player-by-player verification.
"""
from datetime import datetime, timezone as utc
from django.db import migrations


FINALS = (
    ("Vaughn Forest Church", datetime(2026, 9, 22, 23, 30, tzinfo=utc.utc), 14, 6),
    ("Hope Hull Church", datetime(2026, 9, 23, 0, 30, tzinfo=utc.utc), 20, 12),
)


def apply_confirmed_finals(apps, schema_editor):
    SportsGame = apps.get_model("platform_sports", "SportsGame")
    SocialEvent = apps.get_model("platform_social", "SocialEvent")

    for opponent, kickoff, runs_for, runs_against in FINALS:
        matches = list(
            SportsGame.objects.filter(
                team__group__name="Bed Springs Baptist",
                team__sport="SOFTBALL",
                opponent_name=opponent,
                start_at=kickoff,
            )[:2]
        )
        # Skip if absent or ambiguous: this must update an existing exact fixture only.
        if len(matches) != 1:
            continue
        game = matches[0]
        if game.status == "CANCELLED" or game.plate_appearances.exists():
            continue
        # Never overwrite scores another scorekeeper may have recorded.
        if (game.runs_for, game.runs_against) != (0, 0):
            continue
        game.status = "FINAL"
        game.runs_for = runs_for
        game.runs_against = runs_against
        game.ended_at = game.end_at or game.start_at
        game.save(update_fields=("status", "runs_for", "runs_against", "ended_at", "updated_at"))
        if game.social_event_id:
            SocialEvent.objects.filter(pk=game.social_event_id).update(status="COMPLETED")


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0015_sportsgamebookphoto"),
    ]
    operations = [
        migrations.RunPython(apply_confirmed_finals, migrations.RunPython.noop),
    ]
