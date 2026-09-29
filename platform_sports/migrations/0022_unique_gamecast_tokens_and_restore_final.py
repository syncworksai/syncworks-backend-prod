import uuid

from django.db import migrations, models
from django.utils import timezone


def repair_gamecast_tokens_and_historical_status(apps, schema_editor):
    SportsGame = apps.get_model("platform_sports", "SportsGame")

    seen = set()
    for game in SportsGame.objects.order_by("id"):
        token = str(game.gamecast_token)
        if token in seen:
            game.gamecast_token = uuid.uuid4()
            game.save(update_fields=("gamecast_token",))
            token = str(game.gamecast_token)
        seen.add(token)

    # A manager used the legacy "Reopen game" button on the already-final
    # Bed Springs 10-9 Freedom book. Restore that historical result to FINAL
    # while preserving the score and all recorded plays.
    SportsGame.objects.filter(
        team__group__name="Bed Springs Baptist",
        opponent_name="Freedom Church",
        runs_for=10,
        runs_against=9,
        status="LIVE",
    ).update(status="FINAL", ended_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0021_finish_verified_hope_hull"),
    ]

    operations = [
        migrations.RunPython(
            repair_gamecast_tokens_and_historical_status,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="sportsgame",
            name="gamecast_token",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
