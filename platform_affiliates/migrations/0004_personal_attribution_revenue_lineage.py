from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("platform_affiliates", "0003_affiliate_health_revenue_source_state_sync"),
    ]

    operations = [
        migrations.CreateModel(
            name="PersonalReferralAttribution",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("referral_code", models.CharField(max_length=32)),
                ("attribution_source", models.CharField(choices=[("LINK", "Referral Link"), ("MANUAL_CODE", "Manual Code"), ("GODMODE_MANUAL", "God Mode Manual")], default="LINK", max_length=30)),
                ("locked_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("admin_note", models.TextField(blank=True, default="")),
                ("effective_from", models.DateField(default=django.utils.timezone.localdate)),
                ("retroactive", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("affiliate", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="personal_attributions", to="platform_affiliates.affiliatepartner")),
                ("assigned_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_personal_affiliate_attributions", to=settings.AUTH_USER_MODEL)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="personal_affiliate_attribution", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddField(
            model_name="affiliatecommissionledger",
            name="personal_attribution",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="commissions", to="platform_affiliates.personalreferralattribution"),
        ),
        migrations.AddField(
            model_name="affiliatecommissionledger",
            name="referred_user",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="affiliate_commissions_generated", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="affiliatecommissionledger",
            name="revenue_source",
            field=models.CharField(choices=[("MARKETPLACE_FEE", "Marketplace 1% Fee"), ("BUSINESS_PLATFORM_FEE", "Business Platform Fee"), ("PLATFORM_FEE", "Legacy Platform Fee"), ("SBO_SUBSCRIPTION", "Business Subscription"), ("GROWTH_OS_SUBSCRIPTION", "Social Media Subscription"), ("HEALTH_SUBSCRIPTION", "Health Subscription"), ("HEALTH_AI_SUBSCRIPTION", "Health AI Subscription"), ("FINANCE_SUBSCRIPTION", "Finance Subscription"), ("PERSONAL_SUBSCRIPTION", "Personal Subscription / Add-on"), ("OTHER_SYNCWORKS_REVENUE", "Other SyncWorks Revenue")], default="PLATFORM_FEE", max_length=40),
        ),
        migrations.AddIndex(model_name="affiliatecommissionledger", index=models.Index(fields=["referred_user", "source_date"], name="pa_comm_user_date_idx")),
        migrations.AddConstraint(
            model_name="affiliatecommissionledger",
            constraint=models.UniqueConstraint(condition=~models.Q(source_reference=""), fields=("affiliate", "revenue_source", "source_reference"), name="pa_commission_source_unique"),
        ),
    ]
