from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("user_accounts", "0050_salesos_schema_sync"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="payment_method",
            field=models.CharField(
                choices=[("CARD", "Card"), ("CASH", "Cash")],
                default="CARD",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="total_amount_cents",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="ticket",
            name="cash_confirmed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="cash_fee_invoiced_month",
            field=models.CharField(blank=True, default="", max_length=7),
        ),
    ]