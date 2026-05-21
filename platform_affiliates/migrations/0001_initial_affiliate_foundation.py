from __future__ import annotations

import django.db.models.deletion
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("user_accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AffiliatePartner",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=180)),
                ("email", models.EmailField(max_length=254)),
                ("phone", models.CharField(blank=True, default="", max_length=32)),
                ("address_line_1", models.CharField(blank=True, default="", max_length=220)),
                ("address_line_2", models.CharField(blank=True, default="", max_length=220)),
                ("city", models.CharField(blank=True, default="", max_length=80)),
                ("state", models.CharField(blank=True, default="", max_length=2)),
                ("zip_code", models.CharField(blank=True, default="", max_length=20)),
                ("code", models.CharField(max_length=32, unique=True)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("ACTIVE", "Active"), ("SUSPENDED", "Suspended"), ("DEACTIVATED", "Deactivated")], default="PENDING", max_length=20)),
                ("commission_rate_bps", models.PositiveIntegerField(default=1000, help_text="1000 bps = 10% of net SyncWorks revenue.")),
                ("payout_provider", models.CharField(choices=[("MANUAL", "Manual"), ("STRIPE", "Stripe"), ("ACH", "ACH"), ("OTHER", "Other")], default="MANUAL", max_length=20)),
                ("payout_email", models.EmailField(blank=True, default="", max_length=254)),
                ("payout_notes", models.TextField(blank=True, default="")),
                ("external_payout_reference", models.CharField(blank=True, default="", max_length=255)),
                ("application_notes", models.TextField(blank=True, default="")),
                ("referral_strategy", models.TextField(blank=True, default="")),
                ("agreement_version", models.CharField(blank=True, default="", max_length=64)),
                ("agreement_accepted_at", models.DateTimeField(blank=True, null=True)),
                ("agreement_accepted_ip", models.GenericIPAddressField(blank=True, null=True)),
                ("agreement_accepted_user_agent", models.TextField(blank=True, default="")),
                ("notes", models.TextField(blank=True, default="")),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approved_affiliates", to=settings.AUTH_USER_MODEL)),
                ("user", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="affiliate_partner", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="AffiliatePayoutBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("period_start", models.DateField()),
                ("period_end", models.DateField()),
                ("total_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("APPROVED", "Approved"), ("PROCESSING", "Processing"), ("PAID", "Paid"), ("FAILED", "Failed")], default="DRAFT", max_length=20)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("external_reference", models.CharField(blank=True, default="", max_length=255)),
                ("notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("affiliate", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payout_batches", to="platform_affiliates.affiliatepartner")),
            ],
            options={
                "ordering": ["-period_end", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="ReferralAttribution",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("referral_code", models.CharField(max_length=32)),
                ("attribution_source", models.CharField(choices=[("LINK", "Referral Link"), ("MANUAL_CODE", "Manual Code"), ("GODMODE_MANUAL", "God Mode Manual")], default="LINK", max_length=30)),
                ("locked_at", models.DateTimeField(default=timezone.now)),
                ("admin_note", models.TextField(blank=True, default="")),
                ("effective_from", models.DateField(default=timezone.localdate)),
                ("retroactive", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("affiliate", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="attributions", to="platform_affiliates.affiliatepartner")),
                ("assigned_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_affiliate_attributions", to=settings.AUTH_USER_MODEL)),
                ("business", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="affiliate_attribution", to="user_accounts.business")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="ReferralClick",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=32)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.TextField(blank=True, default="")),
                ("landing_path", models.CharField(blank=True, default="", max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("affiliate", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="referral_clicks", to="platform_affiliates.affiliatepartner")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="AffiliateAuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(max_length=120)),
                ("before_json", models.JSONField(blank=True, default=dict)),
                ("after_json", models.JSONField(blank=True, default=dict)),
                ("note", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="affiliate_audit_logs", to=settings.AUTH_USER_MODEL)),
                ("affiliate", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="audit_logs", to="platform_affiliates.affiliatepartner")),
                ("business", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="affiliate_audit_logs", to="user_accounts.business")),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="AffiliateCommissionLedger",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("revenue_source", models.CharField(choices=[("PLATFORM_FEE", "Platform Fee"), ("SBO_SUBSCRIPTION", "SBO Subscription"), ("GROWTH_OS_SUBSCRIPTION", "Growth OS Subscription"), ("OTHER_SYNCWORKS_REVENUE", "Other SyncWorks Revenue")], default="PLATFORM_FEE", max_length=40)),
                ("gross_revenue_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=12)),
                ("net_syncworks_revenue_amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("commission_rate_bps", models.PositiveIntegerField()),
                ("commission_amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("APPROVED", "Approved"), ("PAID", "Paid"), ("VOID", "Void"), ("CLAWED_BACK", "Clawed Back")], default="PENDING", max_length=20)),
                ("source_reference", models.CharField(help_text="Unique reference from invoice, subscription, webhook, or manual source.", max_length=255)),
                ("source_date", models.DateField()),
                ("memo", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("affiliate", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="commission_ledger", to="platform_affiliates.affiliatepartner")),
                ("attribution", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="commission_ledger", to="platform_affiliates.referralattribution")),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="affiliate_commissions", to="user_accounts.business")),
                ("payout_batch", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="commission_items", to="platform_affiliates.affiliatepayoutbatch")),
            ],
            options={
                "ordering": ["-source_date", "-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="affiliatepartner",
            index=models.Index(fields=["code"], name="platform_af_code_823f90_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliatepartner",
            index=models.Index(fields=["status"], name="platform_af_status_fa27e8_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliatepartner",
            index=models.Index(fields=["email"], name="platform_af_email_a5ef01_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliatepayoutbatch",
            index=models.Index(fields=["affiliate", "status"], name="platform_af_affilia_b1f865_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliatepayoutbatch",
            index=models.Index(fields=["period_start", "period_end"], name="platform_af_period__440c21_idx"),
        ),
        migrations.AddIndex(
            model_name="referralattribution",
            index=models.Index(fields=["referral_code"], name="platform_af_referra_68fafa_idx"),
        ),
        migrations.AddIndex(
            model_name="referralattribution",
            index=models.Index(fields=["affiliate", "created_at"], name="platform_af_affilia_f8fc68_idx"),
        ),
        migrations.AddIndex(
            model_name="referralattribution",
            index=models.Index(fields=["effective_from"], name="platform_af_effect_4d7101_idx"),
        ),
        migrations.AddIndex(
            model_name="referralclick",
            index=models.Index(fields=["code"], name="platform_af_code_8d881f_idx"),
        ),
        migrations.AddIndex(
            model_name="referralclick",
            index=models.Index(fields=["created_at"], name="platform_af_created_85e483_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliateauditlog",
            index=models.Index(fields=["action"], name="platform_af_action_05090d_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliateauditlog",
            index=models.Index(fields=["affiliate", "created_at"], name="platform_af_affilia_4c7b0e_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliateauditlog",
            index=models.Index(fields=["business", "created_at"], name="platform_af_busines_8c3ccf_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliatecommissionledger",
            index=models.Index(fields=["affiliate", "status"], name="platform_af_affilia_e52213_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliatecommissionledger",
            index=models.Index(fields=["business", "source_date"], name="platform_af_busines_077973_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliatecommissionledger",
            index=models.Index(fields=["revenue_source"], name="platform_af_revenue_70b48d_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliatecommissionledger",
            index=models.Index(fields=["source_reference"], name="platform_af_source__87317b_idx"),
        ),
        migrations.AddConstraint(
            model_name="affiliatecommissionledger",
            constraint=models.UniqueConstraint(fields=("revenue_source", "source_reference"), name="unique_affiliate_commission_source_reference"),
        ),
    ]