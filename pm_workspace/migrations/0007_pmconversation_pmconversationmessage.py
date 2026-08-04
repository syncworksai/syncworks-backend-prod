from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("pm_workspace", "0006_pmpropertyowner"),
    ]

    operations = [
        migrations.CreateModel(
            name="PMConversation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(choices=[("TENANT", "Tenant"), ("INVESTOR", "Investor"), ("MAINTENANCE", "Maintenance")], max_length=20)),
                ("status", models.CharField(choices=[("OPEN", "Open"), ("WAITING_PM", "Waiting on PM"), ("WAITING_REQUESTER", "Waiting on requester"), ("RESOLVED", "Resolved")], default="OPEN", max_length=24)),
                ("subject", models.CharField(max_length=220)),
                ("requester_name", models.CharField(blank=True, max_length=180)),
                ("requester_email", models.EmailField(blank=True, max_length=254)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_pm_conversations", to=settings.AUTH_USER_MODEL)),
                ("ledger_entry", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="information_requests", to="pm_workspace.pmledgerentry")),
                ("property_owner", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="conversations", to="pm_workspace.pmpropertyowner")),
                ("tenant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="conversations", to="pm_workspace.pmtenant")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="conversations", to="pm_workspace.pmworkspace")),
            ],
            options={"ordering": ["-updated_at", "-id"]},
        ),
        migrations.CreateModel(
            name="PMConversationMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sender_role", models.CharField(choices=[("PM", "Property management"), ("TENANT", "Tenant"), ("INVESTOR", "Investor"), ("SYSTEM", "System")], max_length=16)),
                ("body", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("conversation", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="pm_workspace.pmconversation")),
                ("sender", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="pm_conversation_messages", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
    ]
