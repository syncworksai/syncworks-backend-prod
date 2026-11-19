from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0140_business_technician_groups"),
    ]

    operations = [
        migrations.AlterField(
            model_name="businessmember",
            name="role",
            field=models.CharField(choices=(('OWNER', 'Owner'), ('MANAGER', 'Manager'), ('DISPATCH', 'Dispatch'), ('ACCOUNTING', 'Accounting'), ('HR', 'Human Resources'), ('TECHNICIAN', 'Technician'), ('TECH', 'Technician (Legacy)')), default="TECHNICIAN", max_length=20),
        ),
        migrations.AlterField(
            model_name="invitecode",
            name="role",
            field=models.CharField(choices=(('OWNER', 'Owner'), ('MANAGER', 'Manager'), ('DISPATCH', 'Dispatch'), ('ACCOUNTING', 'Accounting'), ('HR', 'Human Resources'), ('TECHNICIAN', 'Technician'), ('TECH', 'Technician (Legacy)')), default="TECHNICIAN", max_length=20),
        ),
    ]
