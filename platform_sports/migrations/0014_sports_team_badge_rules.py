from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("platform_sports", "0013_player_cards_badges")]
    operations = [migrations.AddField(model_name="sportsteam", name="badge_rules", field=models.JSONField(blank=True, default=dict))]
