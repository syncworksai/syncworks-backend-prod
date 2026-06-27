from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("user_accounts", "0101_communication_preference"),
    ]

    operations = [
        migrations.CreateModel(
            name="TicketConversationReadState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scope", models.CharField(choices=[("PERSONAL", "Personal"), ("BUSINESS", "Business")], max_length=16)),
                ("last_read_at", models.DateTimeField(blank=True, null=True)),
                ("muted", models.BooleanField(default=False)),
                ("pinned", models.BooleanField(default=False)),
                ("needs_attention", models.BooleanField(default=False)),
                ("attention_reason", models.CharField(blank=True, default="", max_length=255)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("last_read_message", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="user_accounts.ticketmessage")),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="conversation_read_states", to="user_accounts.ticket")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ticket_conversation_read_states", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="ticketconversationreadstate",
            constraint=models.UniqueConstraint(fields=("user", "ticket", "scope"), name="uniq_ticket_conversation_read_state"),
        ),
        migrations.AddIndex(
            model_name="ticketconversationreadstate",
            index=models.Index(fields=["user", "scope", "needs_attention"], name="ua_tcrs_user_scope_attention_idx"),
        ),
        migrations.AddIndex(
            model_name="ticketconversationreadstate",
            index=models.Index(fields=["ticket", "scope"], name="ua_tcrs_ticket_scope_idx"),
        ),
    ]
