from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("platform_social", "0009_card_poker_rooms"),
    ]

    operations = [
        migrations.AddField(
            model_name="cardpokerroom",
            name="admission_open",
            field=models.BooleanField(default=True, help_text="Whether approved club members can join between hands."),
        ),
        migrations.AddField(
            model_name="cardpokerroom",
            name="hand_active",
            field=models.BooleanField(default=False, help_text="Reserved for the authoritative multiplayer hand engine; seat changes are blocked while active."),
        ),
    ]
