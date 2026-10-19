from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0135_finance_debt_payment"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformBusinessProspect",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("company_name", models.CharField(max_length=200)),
                ("contact_name", models.CharField(blank=True, default="", max_length=160)),
                ("email", models.EmailField(blank=True, db_index=True, default="", max_length=254)),
                ("phone", models.CharField(blank=True, default="", max_length=40)),
                ("industry", models.CharField(blank=True, default="", max_length=100)),
                ("interests", models.JSONField(blank=True, default=list)),
                ("notes", models.TextField(blank=True, default="")),
                ("next_action", models.CharField(blank=True, default="", max_length=240)),
                ("follow_up_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("status", models.CharField(choices=[("NEW", "New"), ("CONTACTED", "Contacted"), ("INVITED", "Invitation sent"), ("DEMO", "Demo / evaluation"), ("REGISTERED", "Signed up"), ("WON", "Activated / won"), ("LOST", "Lost")], db_index=True, default="NEW", max_length=20)),
                ("invitation_token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("last_invited_at", models.DateTimeField(blank=True, null=True)),
                ("signed_up_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="platform_prospects_created", to=settings.AUTH_USER_MODEL)),
                ("linked_business", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="platform_acquisition_prospects", to="user_accounts.business")),
            ],
            options={"ordering": ["-updated_at", "-id"]},
        ),
        migrations.CreateModel(
            name="PlatformProspectActivity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("NOTE", "Note"), ("CALL", "Call"), ("EMAIL", "Email"), ("INVITATION", "Invitation handed to email backend"), ("STATUS", "Stage change"), ("MEETING", "Meeting / demo")], db_index=True, max_length=20)),
                ("subject", models.CharField(blank=True, default="", max_length=200)),
                ("body", models.TextField(blank=True, default="")),
                ("recipient", models.EmailField(blank=True, default="", max_length=254)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="platform_prospect_activities", to=settings.AUTH_USER_MODEL)),
                ("prospect", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="activities", to="user_accounts.platformbusinessprospect")),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.AddIndex(
            model_name="platformbusinessprospect",
            index=models.Index(fields=["status", "follow_up_at"], name="ua_pbp_status_follow_idx"),
        ),
    ]
