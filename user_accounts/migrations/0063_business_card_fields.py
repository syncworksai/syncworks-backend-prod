# backend/user_accounts/migrations/0063_business_card_fields.py
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0062_cashfeeinvoice_attempt_count_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="business",
            name="headline",
            field=models.CharField(max_length=160, blank=True, default=""),
        ),
        migrations.AddField(
            model_name="business",
            name="services_text",
            field=models.CharField(max_length=320, blank=True, default=""),
        ),
        migrations.AddField(
            model_name="business",
            name="address",
            field=models.CharField(max_length=220, blank=True, default=""),
        ),
        migrations.AddField(
            model_name="business",
            name="website",
            field=models.CharField(max_length=220, blank=True, default=""),
        ),
        migrations.AddField(
            model_name="business",
            name="business_card_code",
            field=models.CharField(
                max_length=64,
                unique=True,
                null=True,
                blank=True,
                default=None,
                help_text="Shareable business card code for customers to add as a favorite (QR/paste).",
            ),
        ),
    ]