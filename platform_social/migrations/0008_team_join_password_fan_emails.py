import os

from django.contrib.auth.hashers import make_password
from django.db import migrations, models


def set_existing_bed_springs_password(apps, schema_editor):
    Group = apps.get_model("platform_social", "SocialGroup")
    matches = list(Group.objects.filter(name__iexact="Bed Springs Baptist", kind="TEAM", is_active=True)[:2])
    # Never guess which group owns the password if names collide.
    configured_secret = os.environ.get("BSB_TEAM_JOIN_PASSWORD", "")
    if len(matches) == 1 and configured_secret and not matches[0].player_join_password_hash:
        matches[0].player_join_password_hash = make_password(configured_secret)
        matches[0].save(update_fields=["player_join_password_hash"])


class Migration(migrations.Migration):
    dependencies = [
        ("platform_social", "0007_scorekeeper_group_logo"),
    ]

    operations = [
        migrations.AddField(
            model_name="socialgroup",
            name="player_join_password_hash",
            field=models.CharField(blank=True, default="", max_length=256),
        ),
        migrations.AddField(
            model_name="groupfollow",
            name="gamecast_email_updates",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(set_existing_bed_springs_password, migrations.RunPython.noop),
    ]
