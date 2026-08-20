from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0126_workforce_ticket_operations"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticketoperationalprofile",
            name="scheduled_start",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ticketoperationalprofile",
            name="scheduled_end",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="ticketoperationalprofile",
            index=models.Index(fields=["scheduled_start", "scheduled_end"], name="ua_ticketops_window_idx"),
        ),
    ]
