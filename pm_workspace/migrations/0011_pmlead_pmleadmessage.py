from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("pm_workspace", "0010_pmpropertyprofile_pmpropertyasset"),
    ]

    operations = [
        migrations.CreateModel(
            name="PMLead",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("stage", models.CharField(choices=[("NEW", "New"), ("CONTACTED", "Contacted"), ("QUALIFIED", "Qualified"), ("REVIEWING", "Showing / reviewing"), ("APPLICATION", "Application"), ("APPROVED", "Approved"), ("LEASE_PENDING", "Lease pending"), ("WON", "Won"), ("LOST", "Lost")], default="NEW", max_length=24)),
                ("lead_type", models.CharField(choices=[("REGULAR", "Regular tenant"), ("CORPORATE", "Corporate leasing"), ("INSURANCE", "Insurance housing"), ("SECTION8", "Section 8 / housing assistance"), ("RELOCATION", "Relocation"), ("OTHER", "Other")], default="REGULAR", max_length=24)),
                ("source", models.CharField(choices=[("FURNISHED_FINDER", "Furnished Finder"), ("ZILLOW", "Zillow"), ("APARTMENTS", "Apartments.com"), ("FACEBOOK", "Facebook"), ("INSTAGRAM", "Instagram"), ("WEBSITE", "Website"), ("PHONE", "Phone"), ("REFERRAL", "Referral"), ("CORPORATE_PARTNER", "Corporate housing partner"), ("INSURANCE_CARRIER", "Insurance carrier"), ("HOUSING_AUTHORITY", "Housing authority"), ("REALTOR", "Realtor"), ("OWNER_REFERRAL", "Owner referral"), ("MANUAL", "Manual"), ("OTHER", "Other")], default="MANUAL", max_length=32)),
                ("source_label", models.CharField(blank=True, max_length=180)),
                ("first_name", models.CharField(blank=True, max_length=100)),
                ("last_name", models.CharField(blank=True, max_length=100)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=40)),
                ("company_name", models.CharField(blank=True, max_length=180)),
                ("requested_start", models.DateField(blank=True, null=True)),
                ("requested_end", models.DateField(blank=True, null=True)),
                ("adults", models.PositiveSmallIntegerField(default=1)),
                ("children", models.PositiveSmallIntegerField(default=0)),
                ("pets", models.PositiveSmallIntegerField(default=0)),
                ("pet_notes", models.CharField(blank=True, max_length=255)),
                ("furnished_requested", models.BooleanField(default=False)),
                ("budget_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("summary", models.TextField(blank=True)),
                ("notes", models.TextField(blank=True)),
                ("classification_confidence", models.PositiveSmallIntegerField(default=0)),
                ("classification_reason", models.CharField(blank=True, max_length=255)),
                ("mailbox_connection_id", models.CharField(blank=True, max_length=64)),
                ("external_thread_id", models.CharField(blank=True, max_length=255)),
                ("source_subject", models.CharField(blank=True, max_length=255)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_pm_leads", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_pm_leads", to=settings.AUTH_USER_MODEL)),
                ("property", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="leads", to="pm_workspace.pmproperty")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="leads", to="pm_workspace.pmworkspace")),
            ],
            options={"ordering": ["-updated_at", "-id"]},
        ),
        migrations.CreateModel(
            name="PMLeadMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("direction", models.CharField(choices=[("INBOUND", "Inbound"), ("OUTBOUND", "Outbound"), ("INTERNAL", "Internal note")], default="INBOUND", max_length=16)),
                ("channel", models.CharField(choices=[("EMAIL", "Email"), ("APP", "SyncWorks"), ("PHONE", "Phone"), ("OTHER", "Other")], default="EMAIL", max_length=16)),
                ("sender_name", models.CharField(blank=True, max_length=180)),
                ("sender_email", models.EmailField(blank=True, max_length=254)),
                ("recipient_email", models.EmailField(blank=True, max_length=254)),
                ("subject", models.CharField(blank=True, max_length=255)),
                ("body", models.TextField(blank=True)),
                ("external_message_id", models.CharField(blank=True, max_length=255)),
                ("external_thread_id", models.CharField(blank=True, max_length=255)),
                ("mailbox_connection_id", models.CharField(blank=True, max_length=64)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("lead", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="messages", to="pm_workspace.pmlead")),
                ("sent_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="pm_lead_messages", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.AddIndex(model_name="pmlead", index=models.Index(fields=["workspace", "stage"], name="pm_workspa_workspa_2aa8b2_idx")),
        migrations.AddIndex(model_name="pmlead", index=models.Index(fields=["workspace", "lead_type"], name="pm_workspa_workspa_f78f33_idx")),
        migrations.AddIndex(model_name="pmlead", index=models.Index(fields=["workspace", "source"], name="pm_workspa_workspa_0a6192_idx")),
        migrations.AddIndex(model_name="pmlead", index=models.Index(fields=["workspace", "email"], name="pm_workspa_workspa_3a0d6e_idx")),
        migrations.AddConstraint(model_name="pmleadmessage", constraint=models.UniqueConstraint(condition=~models.Q(external_message_id=""), fields=("lead", "external_message_id"), name="uniq_pm_lead_external_message")),
    ]
