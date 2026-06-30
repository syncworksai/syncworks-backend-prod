from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0108_automation_rules"),
    ]

    operations = [
        migrations.AddField(
            model_name="business",
            name="exclude_from_kpis",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text="Exclude this business and its operational records from production KPI totals.",
            ),
        ),
        migrations.AddField(
            model_name="business",
            name="is_demo",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text="Marks an isolated demonstration or training workspace.",
            ),
        ),
    ]
