# Generated manually for marketplace intake native fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0075_alter_businessdailykpi_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicerequest",
            name="priority",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="needed_by_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="preferred_time_window",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="preferred_start_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="preferred_end_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="intake_payload",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]