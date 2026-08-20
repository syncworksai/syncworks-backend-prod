from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0127_ticket_operational_scheduled_window"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticketoperationalprofile",
            name="actual_started_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="ticketoperationalprofile",
            name="actual_finished_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ticketoperationalprofile",
            name="actual_work_seconds",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
