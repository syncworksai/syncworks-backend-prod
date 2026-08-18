from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("platform_social", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SocialMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("CHAT", "Chat"), ("ANNOUNCEMENT", "Announcement"), ("SYSTEM", "System")], default="CHAT", max_length=16)),
                ("body", models.TextField(max_length=5000)),
                ("edited_at", models.DateTimeField(blank=True, null=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("event", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="social_messages", to="platform_social.socialevent")),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="social_messages", to="platform_social.socialgroup")),
                ("sender", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="social_messages_sent", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("created_at", "id")},
        ),
        migrations.AddIndex(
            model_name="socialmessage",
            index=models.Index(fields=["group", "event", "created_at"], name="social_msg_group_event"),
        ),
        migrations.AddIndex(
            model_name="socialmessage",
            index=models.Index(fields=["sender", "created_at"], name="social_msg_sender_time"),
        ),
    ]
