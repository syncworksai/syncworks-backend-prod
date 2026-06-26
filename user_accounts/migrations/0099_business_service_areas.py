from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0077_verified_registration_identity"),
    ]

    operations = [
        migrations.AddField(
            model_name="business",
            name="service_areas",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Structured expanded coverage rules. Live matching continues using base ZIP and radius until Build 3B.",
            ),
        ),
    ]
