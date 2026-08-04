from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("pm_workspace", "0007_pmconversation_pmconversationmessage"),
    ]

    operations = [
        migrations.CreateModel(
            name="PMPropertyDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(choices=[("LEASE", "Lease agreement"), ("LEASE_ADDENDUM", "Lease addendum"), ("MANAGEMENT_AGREEMENT", "Property management agreement"), ("OWNERSHIP", "Ownership / management change"), ("SECTION8", "Section 8 / housing authority"), ("RENT_INCREASE", "Rent increase request"), ("MOVE_IN_INSPECTION", "Move-in inspection"), ("MOVE_OUT_INSPECTION", "Move-out inspection"), ("SECURITY_DEPOSIT", "Security deposit"), ("PAYMENT_ARRANGEMENT", "Payment arrangement"), ("NOTICE", "Notice / legal"), ("OPERATING_STATEMENT", "Operating statement"), ("INSURANCE", "Insurance"), ("IDENTITY_TAX", "Identity / tax"), ("OTHER", "Other")], max_length=40)),
                ("title", models.CharField(max_length=220)),
                ("document", models.FileField(blank=True, null=True, upload_to="pm/documents/%Y/%m/")),
                ("source_url", models.URLField(blank=True)),
                ("source_name", models.CharField(blank=True, max_length=255)),
                ("state_code", models.CharField(blank=True, max_length=2)),
                ("housing_authority", models.CharField(blank=True, max_length=180)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("ACTIVE", "Active"), ("PENDING_SIGNATURE", "Pending signature"), ("SIGNED", "Signed"), ("SUBMITTED", "Submitted"), ("APPROVED", "Approved"), ("EXPIRED", "Expired"), ("ARCHIVED", "Archived")], default="ACTIVE", max_length=24)),
                ("effective_date", models.DateField(blank=True, null=True)),
                ("expiration_date", models.DateField(blank=True, null=True)),
                ("signed_date", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("checklist_key", models.CharField(blank=True, max_length=100)),
                ("extracted_terms", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_pm_property_documents", to=settings.AUTH_USER_MODEL)),
                ("lease", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="property_documents", to="pm_workspace.pmlease")),
                ("property", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="documents", to="pm_workspace.pmproperty")),
                ("property_owner", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="documents", to="pm_workspace.pmpropertyowner")),
                ("tenant", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="property_documents", to="pm_workspace.pmtenant")),
                ("workspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="property_documents", to="pm_workspace.pmworkspace")),
            ],
            options={"ordering": ["-updated_at", "-id"]},
        ),
        migrations.AddIndex(model_name="pmpropertydocument", index=models.Index(fields=["workspace", "property", "category"], name="pm_workspac_workspa_9e9085_idx")),
        migrations.AddIndex(model_name="pmpropertydocument", index=models.Index(fields=["workspace", "status"], name="pm_workspac_workspa_09e3c7_idx")),
    ]
