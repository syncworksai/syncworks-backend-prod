from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("platform_affiliates", "0004_personal_attribution_revenue_lineage"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="affiliatecommissionledger",
            name="unique_affiliate_commission_source_reference",
        ),
        migrations.AlterField(
            model_name="affiliatecommissionledger",
            name="business",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="affiliate_commissions",
                to="user_accounts.business",
            ),
        ),
        migrations.AlterField(
            model_name="affiliatecommissionledger",
            name="attribution",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="commission_ledger",
                to="platform_affiliates.referralattribution",
            ),
        ),
        migrations.AlterField(
            model_name="affiliatecommissionledger",
            name="source_reference",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Unique reference from invoice, subscription, webhook, or manual source.",
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name="affiliatecommissionledger",
            name="source_date",
            field=models.DateField(default=django.utils.timezone.localdate),
        ),
    ]
