from __future__ import annotations

from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0071_userbillingprofile_beta_access_code_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ServiceCatalogItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160)),
                ("sku", models.CharField(blank=True, default="", max_length=64)),
                ("description", models.TextField(blank=True, default="")),
                ("item_type", models.CharField(choices=[("SERVICE", "Service"), ("PRODUCT", "Product"), ("FEE", "Fee")], default="SERVICE", max_length=20)),
                ("unit_label", models.CharField(blank=True, default="", help_text="Examples: each, hour, visit, ride, yard, room", max_length=32)),
                ("default_quantity", models.DecimalField(decimal_places=2, default=Decimal("1.00"), max_digits=10)),
                ("unit_price", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("unit_cost", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10)),
                ("is_active", models.BooleanField(default=True)),
                ("is_featured", models.BooleanField(default=False)),
                ("requires_quote", models.BooleanField(default=False, help_text="If true, this item is intended to go through quote approval before invoicing.")),
                ("allow_direct_checkout", models.BooleanField(default=False, help_text="If true, this item can later be used in direct-order / fixed-price flows.")),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "business",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="service_catalog_items",
                        to="user_accounts.business",
                    ),
                ),
            ],
            options={
                "ordering": ["sort_order", "name", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="servicecatalogitem",
            index=models.Index(fields=["business", "is_active", "sort_order"], name="user_accoun_busines_8b88d9_idx"),
        ),
        migrations.AddIndex(
            model_name="servicecatalogitem",
            index=models.Index(fields=["business", "item_type", "is_active"], name="user_accoun_busines_1d1534_idx"),
        ),
        migrations.AddIndex(
            model_name="servicecatalogitem",
            index=models.Index(fields=["business", "name"], name="user_accoun_busines_7268f7_idx"),
        ),
        migrations.AddIndex(
            model_name="servicecatalogitem",
            index=models.Index(fields=["business", "sku"], name="user_accoun_busines_1b575f_idx"),
        ),
        migrations.AddConstraint(
            model_name="servicecatalogitem",
            constraint=models.UniqueConstraint(
                condition=models.Q(("sku", ""), _negated=True),
                fields=("business", "sku"),
                name="uniq_service_catalog_item_business_sku_nonblank",
            ),
        ),
    ]