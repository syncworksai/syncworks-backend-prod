from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("platform_social", "0004_group_invites_collect_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="socialevent",
            name="flyer_image",
            field=models.ImageField(blank=True, null=True, upload_to="social/event_flyers/%Y/%m/"),
        ),
    ]
