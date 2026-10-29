from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("user_accounts", "0137_business_pilot_tracking")]
    operations = [
        migrations.AddField(model_name="cashfeeinvoice", name="last_reminder_sent_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="cashfeeinvoice", name="reminder_count", field=models.PositiveIntegerField(default=0)),
    ]
