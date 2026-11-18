from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("user_accounts","0139_service_catalog_request_settings")]
    operations = [
        migrations.CreateModel(
            name="BusinessTechnicianGroup",
            fields=[
                ("id",models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name="ID")),
                ("name",models.CharField(max_length=80)),
                ("created_at",models.DateTimeField(auto_now_add=True)),
                ("business",models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name="technician_groups",to="user_accounts.business")),
            ],
            options={"ordering":["name"]},
        ),
        migrations.AddConstraint(
            model_name="businesstechniciangroup",
            constraint=models.UniqueConstraint(fields=("business","name"),name="ua_techgroup_business_name_uniq"),
        ),
        migrations.AddField(
            model_name="workforceprofile",name="technician_group",
            field=models.ForeignKey(to="user_accounts.businesstechniciangroup",on_delete=django.db.models.deletion.SET_NULL,null=True,blank=True,related_name="technicians"),
        ),
    ]
