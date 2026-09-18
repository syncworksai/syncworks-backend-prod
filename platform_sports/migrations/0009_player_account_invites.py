import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("platform_sports", "0008_commissioner_schedule_tournaments"),
    ]

    operations = [
        migrations.CreateModel(
            name="SportsPlayerInvite",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(max_length=254)),
                ("token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("status", models.CharField(choices=[("INVITED", "Invited"), ("ACCEPTED", "Accepted"), ("REVOKED", "Revoked")], default="INVITED", max_length=12)),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("accepted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sports_player_invites_accepted", to=settings.AUTH_USER_MODEL)),
                ("invited_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sports_player_invites_sent", to=settings.AUTH_USER_MODEL)),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="account_invites", to="platform_sports.sportsplayer")),
            ],
            options={
                "ordering": ("-created_at", "-id"),
                "indexes": [
                    models.Index(fields=["player", "status"], name="sports_player_invite_state"),
                    models.Index(fields=["email", "status"], name="sports_player_invite_email"),
                ],
            },
        ),
    ]
