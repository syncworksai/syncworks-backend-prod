from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0138_sync_assist_job"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicecatalogitem",
            name="service_category",
            field=models.CharField(max_length=100, default="", blank=True, help_text="Business-defined group, e.g. Plumbing or Appliances"),
        ),
        migrations.AddField(
            model_name="servicecatalogitem",
            name="required_skills",
            field=models.JSONField(default=list, blank=True),
        ),
        migrations.AddField(
            model_name="servicecatalogitem",
            name="estimated_duration_minutes",
            field=models.PositiveIntegerField(default=60),
        ),
    ]
