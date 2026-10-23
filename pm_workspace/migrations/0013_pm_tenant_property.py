from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[("pm_workspace","0012_pm_workspace_access")]
    operations=[
        migrations.AddField(
            model_name="pmtenant",
            name="property",
            field=models.ForeignKey(
                to="pm_workspace.pmproperty",
                null=True,blank=True,on_delete=django.db.models.deletion.SET_NULL,
                related_name="resident_records",
            ),
        ),
    ]
