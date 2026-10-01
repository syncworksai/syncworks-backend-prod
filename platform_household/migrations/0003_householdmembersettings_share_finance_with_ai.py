from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("platform_household", "0002_sharedtask_recurrence_weather"),
    ]

    operations = [
        migrations.AddField(
            model_name="householdmembersettings",
            name="share_finance_with_ai",
            field=models.BooleanField(default=False),
        ),
    ]
