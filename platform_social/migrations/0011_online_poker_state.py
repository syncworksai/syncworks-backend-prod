from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("platform_social", "0010_poker_admission_and_hand_state")]
    operations = [
        migrations.AddField(
            model_name="cardpokerroom",
            name="game_state",
            field=models.JSONField(default=dict, blank=True, help_text="Server-private authoritative game state; never serialized to clients."),
        ),
        migrations.AlterField(
            model_name="cardpokerseat",
            name="virtual_chips_cents",
            field=models.IntegerField(default=0),
        ),
    ]
