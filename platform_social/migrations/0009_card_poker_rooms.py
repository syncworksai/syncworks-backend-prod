from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("platform_social", "0008_team_join_password_fan_emails"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CardPokerRoom",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80)),
                ("capacity", models.PositiveSmallIntegerField(default=6)),
                ("virtual_buy_in_cents", models.PositiveIntegerField(default=2000)),
                ("state", models.CharField(choices=[("WAITING", "Waiting"), ("DEALER", "Dealer choosing"), ("READY", "Ready to play"), ("CLOSED", "Closed")], default="WAITING", max_length=12)),
                ("dealer_position", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("game_code", models.CharField(blank=True, max_length=24)),
                ("ante_cents", models.PositiveIntegerField(default=25)),
                ("pot_cap_cents", models.PositiveIntegerField(default=5000)),
                ("game_selection", models.CharField(default="DEALER", max_length=8)),
                ("hand_number", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="created_card_rooms", to=settings.AUTH_USER_MODEL)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="card_rooms", to="platform_social.socialgroup")),
            ],
            options={"ordering": ("-updated_at", "-id")},
        ),
        migrations.CreateModel(
            name="CardPokerSeat",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.PositiveSmallIntegerField()),
                ("is_computer", models.BooleanField(default=False)),
                ("nickname", models.CharField(blank=True, max_length=32)),
                ("virtual_chips_cents", models.PositiveIntegerField(default=0)),
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                ("room", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="seats", to="platform_social.cardpokerroom")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="card_room_seats", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("position", "id")},
        ),
        migrations.AddIndex(model_name="cardpokerroom", index=models.Index(fields=["group", "state"], name="social_card_room_group_state")),
        migrations.AddConstraint(model_name="cardpokerseat", constraint=models.UniqueConstraint(fields=("room", "position"), name="social_card_unique_position")),
        migrations.AddConstraint(model_name="cardpokerseat", constraint=models.UniqueConstraint(condition=Q(user__isnull=False), fields=("room", "user"), name="social_card_unique_user")),
    ]
