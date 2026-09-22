from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("platform_social", "0006_social_categories_followers_payment_profile"),
    ]

    operations = [
        migrations.AddField(
            model_name="socialgroup",
            name="logo_image",
            field=models.ImageField(blank=True, null=True, upload_to="social/group_logos/%Y/%m/"),
        ),
        migrations.AlterField(
            model_name="groupmembership",
            name="role",
            field=models.CharField(
                choices=[
                    ("OWNER", "Owner"),
                    ("DIRECTOR", "Director"),
                    ("MANAGER", "Manager / Coach"),
                    ("SCOREKEEPER", "Scorekeeper"),
                    ("MEMBER", "Member"),
                ],
                default="MEMBER",
                max_length=12,
            ),
        ),
        migrations.AlterField(
            model_name="groupinvitelink",
            name="role",
            field=models.CharField(
                choices=[
                    ("OWNER", "Owner"),
                    ("DIRECTOR", "Director"),
                    ("MANAGER", "Manager / Coach"),
                    ("SCOREKEEPER", "Scorekeeper"),
                    ("MEMBER", "Member"),
                ],
                default="MEMBER",
                max_length=12,
            ),
        ),
    ]
