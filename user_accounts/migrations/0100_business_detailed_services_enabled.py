from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0099_business_service_areas"),
    ]

    operations = [
        migrations.AddField(
            model_name="business",
            name="detailed_services_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "When enabled, marketplace routing only matches exact selected "
                    "leaf services. When disabled, legacy broad categories include descendants."
                ),
            ),
        ),
    ]
