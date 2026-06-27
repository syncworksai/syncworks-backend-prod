from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0102_ticket_conversation_read_state"),
    ]

    operations = [
        migrations.CreateModel(
            name="TrackableAsset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("asset_type", models.CharField(choices=[("VEHICLE", "Vehicle"), ("EQUIPMENT", "Equipment"), ("PROPERTY", "Property"), ("PRODUCT", "Product"), ("INVENTORY", "Inventory"), ("ORDER", "Order"), ("TOOL", "Tool"), ("APPLIANCE", "Appliance"), ("SYSTEM", "System"), ("CUSTOM", "Custom")], default="CUSTOM", max_length=24)),
                ("name", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True, default="")),
                ("status", models.CharField(choices=[("ACTIVE", "Active"), ("IN_SERVICE", "In Service"), ("HOLDING", "Holding"), ("BLOCKED", "Blocked"), ("RETIRED", "Retired")], default="ACTIVE", max_length=24)),
                ("make", models.CharField(blank=True, default="", max_length=100)),
                ("model", models.CharField(blank=True, default="", max_length=100)),
                ("year", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("location", models.CharField(blank=True, default="", max_length=160)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("public_token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="trackable_assets", to="user_accounts.business")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="trackable_assets_created", to=settings.AUTH_USER_MODEL)),
                ("customer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="trackable_assets", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["name", "id"]},
        ),
        migrations.CreateModel(
            name="AssetIdentifier",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("identifier_type", models.CharField(choices=[("SYNCWORKS_QR", "SyncWorks QR"), ("BARCODE", "Barcode"), ("UPC", "UPC"), ("SKU", "SKU"), ("VIN", "VIN"), ("LICENSE_PLATE", "License Plate"), ("SERIAL_NUMBER", "Serial Number"), ("VENDOR_PART_NUMBER", "Vendor Part Number"), ("KEY_TAG", "Key Tag"), ("PURCHASE_ORDER", "Purchase Order"), ("TABLE_CODE", "Table Code"), ("SHELF_CODE", "Shelf Code"), ("CUSTOM", "Custom")], default="CUSTOM", max_length=32)),
                ("value", models.CharField(max_length=255)),
                ("normalized_value", models.CharField(max_length=255)),
                ("source", models.CharField(blank=True, default="", max_length=120)),
                ("is_primary", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("asset", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="identifiers", to="user_accounts.trackableasset")),
            ],
            options={"ordering": ["-is_primary", "identifier_type", "id"]},
        ),
        migrations.CreateModel(
            name="TicketAssetLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("PRIMARY", "Primary"), ("RELATED", "Related"), ("MATERIAL", "Material"), ("RESOURCE", "Resource")], default="PRIMARY", max_length=20)),
                ("notes", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("asset", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ticket_links", to="user_accounts.trackableasset")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ticket_asset_links_created", to=settings.AUTH_USER_MODEL)),
                ("ticket", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="asset_links", to="user_accounts.ticket")),
            ],
            options={"ordering": ["ticket_id", "id"]},
        ),
        migrations.AddIndex(model_name="trackableasset", index=models.Index(fields=["business", "asset_type", "is_active"], name="ua_asset_business_type_idx")),
        migrations.AddIndex(model_name="trackableasset", index=models.Index(fields=["business", "customer"], name="ua_asset_business_customer_idx")),
        migrations.AddIndex(model_name="trackableasset", index=models.Index(fields=["business", "status"], name="ua_asset_business_status_idx")),
        migrations.AddConstraint(model_name="assetidentifier", constraint=models.UniqueConstraint(fields=("asset", "identifier_type", "normalized_value"), name="ua_asset_identifier_asset_unique")),
        migrations.AddIndex(model_name="assetidentifier", index=models.Index(fields=["identifier_type", "normalized_value"], name="ua_asset_identifier_lookup_idx")),
        migrations.AddIndex(model_name="assetidentifier", index=models.Index(fields=["asset", "is_active"], name="ua_asset_identifier_active_idx")),
        migrations.AddConstraint(model_name="ticketassetlink", constraint=models.UniqueConstraint(fields=("ticket", "asset", "role"), name="ua_ticket_asset_role_unique")),
        migrations.AddIndex(model_name="ticketassetlink", index=models.Index(fields=["ticket", "role"], name="ua_ticket_asset_role_idx")),
        migrations.AddIndex(model_name="ticketassetlink", index=models.Index(fields=["asset", "created_at"], name="ua_asset_ticket_created_idx")),
    ]
