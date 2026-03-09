from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0060_cashfeeinvoice"),
    ]

    operations = [
        # -------- Business: subscriptions-only waiver --------
        migrations.AddField(
            model_name="business",
            name="subscriptions_exempt",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="business",
            name="subscriptions_exempt_reason",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="business",
            name="subscriptions_exempt_until",
            field=models.DateField(blank=True, null=True),
        ),

        # -------- PromoCode: subscriptions-only flag --------
        migrations.AddField(
            model_name="promocode",
            name="waive_subscriptions",
            field=models.BooleanField(default=False),
        ),

        # -------- PromoCode: safer default (FULL exemption should NOT be default True) --------
        migrations.AlterField(
            model_name="promocode",
            name="billing_exempt",
            field=models.BooleanField(default=False),
        ),
    ]