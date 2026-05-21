from __future__ import annotations

import django.db.models.deletion

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("platform_affiliates", "0001_initial_affiliate_foundation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AffiliateAgreementTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("version", models.CharField(max_length=64, unique=True)),
                ("title", models.CharField(default="SyncWorks Affiliate Agreement", max_length=180)),
                ("body", models.TextField()),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="AffiliateAgreementAcceptance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("agreement_version", models.CharField(max_length=64)),
                ("agreement_title", models.CharField(max_length=180)),
                ("agreement_body_snapshot", models.TextField()),
                ("accepted_at", models.DateTimeField()),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("affiliate", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="agreement_acceptances", to="platform_affiliates.affiliatepartner")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="affiliate_agreement_acceptances", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-accepted_at"],
            },
        ),
        migrations.AddIndex(
            model_name="affiliateagreementtemplate",
            index=models.Index(fields=["version"], name="platform_af_version_9e6798_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliateagreementtemplate",
            index=models.Index(fields=["is_active"], name="platform_af_is_acti_4262a5_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliateagreementacceptance",
            index=models.Index(fields=["affiliate", "accepted_at"], name="platform_af_affilia_9122ae_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliateagreementacceptance",
            index=models.Index(fields=["agreement_version"], name="platform_af_agreeme_6317c2_idx"),
        ),
    ]