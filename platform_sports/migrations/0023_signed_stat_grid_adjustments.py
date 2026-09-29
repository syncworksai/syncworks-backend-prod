from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("platform_sports", "0022_unique_gamecast_tokens_and_restore_final"),
    ]

    operations = [
        migrations.AlterField(model_name="softballstatledgerentry", name="games", field=models.IntegerField(default=0)),
        migrations.AlterField(model_name="softballstatledgerentry", name="pa", field=models.IntegerField(default=0)),
        migrations.AlterField(model_name="softballstatledgerentry", name="ab", field=models.IntegerField(default=0)),
        migrations.AlterField(model_name="softballstatledgerentry", name="hits", field=models.IntegerField(default=0)),
        migrations.AlterField(model_name="softballstatledgerentry", name="doubles", field=models.IntegerField(default=0)),
        migrations.AlterField(model_name="softballstatledgerentry", name="triples", field=models.IntegerField(default=0)),
        migrations.AlterField(model_name="softballstatledgerentry", name="home_runs", field=models.IntegerField(default=0)),
        migrations.AlterField(model_name="softballstatledgerentry", name="walks", field=models.IntegerField(default=0)),
        migrations.AlterField(model_name="softballstatledgerentry", name="sac_flies", field=models.IntegerField(default=0)),
        migrations.AlterField(model_name="softballstatledgerentry", name="rbi", field=models.IntegerField(default=0)),
        migrations.AlterField(model_name="softballstatledgerentry", name="runs", field=models.IntegerField(default=0)),
    ]
