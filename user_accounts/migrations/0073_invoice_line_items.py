from __future__ import annotations

from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0072_add_service_catalog"),
    ]

    operations = [
        migrations.CreateModel(
            name="InvoiceLineItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True, default="")),
                ("item_type", models.CharField(choices=[("SERVICE", "Service"), ("PRODUCT", "Product"), ("FEE", "Fee"), ("CUSTOM", "Custom")], default="CUSTOM", max_length=20)),
                ("unit_label", models.CharField(blank=True, default="", max_length=32)),
                ("quantity", models.DecimalField(decimal_places=2, default=Decimal("1.00"), max_digits=10)),
                ("unit_price", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("unit_cost", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("line_subtotal", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "catalog_item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="invoice_line_items",
                        to="user_accounts.servicecatalogitem",
                    ),
                ),
                (
                    "invoice",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="line_items",
                        to="user_accounts.invoice",
                    ),
                ),
            ],
            options={
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="invoicelineitem",
            index=models.Index(fields=["invoice", "sort_order"], name="user_accoun_invoice_2969c5_idx"),
        ),
        migrations.AddIndex(
            model_name="invoicelineitem",
            index=models.Index(fields=["invoice", "catalog_item"], name="user_accoun_invoice_9e4025_idx"),
        ),
    ]