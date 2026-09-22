from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("platform_sports", "0011_gamecast_controls")]

    operations = [
        migrations.AddField(
            model_name="sportsplayerinvite",
            name="requested_role",
            field=models.CharField(
                choices=[("MEMBER", "Member"), ("SCOREKEEPER", "Scorekeeper"), ("MANAGER", "Manager / Coach"), ("DIRECTOR", "Director")],
                default="MEMBER",
                max_length=12,
            ),
        ),
    ]
