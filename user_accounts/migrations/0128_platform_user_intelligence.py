from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0127_ticket_operational_scheduled_window"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformuserclassification",
            name="intelligence",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
