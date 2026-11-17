from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import customer_health.models


class Migration(migrations.Migration):
    dependencies = [
        ("customer_health", "0002_customerhealthfeedback"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ForgePersonalProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("focus_areas", models.JSONField(blank=True, default=customer_health.models.default_list)),
                ("coaching_style", models.CharField(default="balanced", max_length=24)),
                ("personal_vision", models.TextField(blank=True, default="")),
                ("current_challenge", models.TextField(blank=True, default="")),
                ("daily_practice", models.TextField(blank=True, default="")),
                ("memory_enabled", models.BooleanField(default=False)),
                ("assessment_completed", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="forge_personal_profile", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "Forge Personal Profile"},
        ),
        migrations.CreateModel(
            name="ForgeConversationEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("chapter_key", models.CharField(db_index=True, max_length=100)),
                ("role", models.CharField(max_length=12)),
                ("text", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="forge_conversation_entries", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.AddIndex(
            model_name="forgeconversationentry",
            index=models.Index(fields=["user", "chapter_key", "created_at"], name="forge_msg_owner_chapter_idx"),
        ),
    ]
