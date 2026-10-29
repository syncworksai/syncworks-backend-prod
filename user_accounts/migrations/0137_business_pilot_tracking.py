from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0136_platform_business_prospects"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformbusinessprospect",
            name="pilot_status",
            field=models.CharField(
                max_length=16, db_index=True, default="NOT_STARTED",
                choices=[
                    ("NOT_STARTED", "Not started"), ("INVITED", "Invited to pilot"),
                    ("ONBOARDING", "Onboarding"), ("TESTING", "Testing workflow"),
                    ("BLOCKED", "Blocked"), ("COMPLETE", "Completed pilot"),
                ],
            ),
        ),
        migrations.AddField(
            model_name="platformbusinessprospect", name="pilot_checks",
            field=models.JSONField(default=dict, blank=True),
        ),
        migrations.AddField(
            model_name="platformbusinessprospect", name="pilot_feedback",
            field=models.TextField(default="", blank=True),
        ),
    ]
