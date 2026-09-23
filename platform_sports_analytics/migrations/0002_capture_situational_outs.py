from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports_analytics", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="softballplaycontext",
            name="outs_before",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, validators=[django.core.validators.MaxValueValidator(2)]
            ),
        ),
    ]
