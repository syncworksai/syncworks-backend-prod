from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("platform_sports", "0025_bed_springs_verified_totals_v26"),
    ]

    operations = [
        migrations.AlterField(
            model_name="softballstatledgerentry",
            name="scope",
            field=models.CharField(
                choices=[
                    ("LEAGUE", "League"),
                    ("TOURNAMENT", "Tournament"),
                    ("COMBINED", "Combined season correction"),
                    ("OTHER", "Other"),
                ],
                default="LEAGUE",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="softballstatledgerentry",
            name="double_plays",
            field=models.IntegerField(default=0),
        ),
    ]
