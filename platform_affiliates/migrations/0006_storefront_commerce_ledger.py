from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def seed_amazon_merchant(apps, schema_editor):
    StorefrontMerchant = apps.get_model("platform_affiliates", "StorefrontMerchant")
    StorefrontMerchant.objects.get_or_create(
        slug="amazon",
        defaults={
            "name": "Amazon",
            "kind": "AMAZON",
            "status": "ACTIVE",
            "allowed_domains": ["amazon.com", "amzn.to"],
            "affiliate_tag_env_key": "AMAZON_ASSOCIATE_TAG",
            "disclosure": "Partner link — SyncWorks may earn a commission from qualifying purchases.",
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("platform_affiliates", "0005_fix_personal_commission_runtime_schema"),
        ("user_accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="StorefrontMerchant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.SlugField(max_length=80, unique=True)),
                ("name", models.CharField(max_length=160)),
                ("kind", models.CharField(choices=[("AMAZON", "Amazon"), ("DIRECT", "Direct partner"), ("OTHER", "Other")], default="OTHER", max_length=20)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("ACTIVE", "Active"), ("DISABLED", "Disabled")], default="PENDING", max_length=20)),
                ("allowed_domains", models.JSONField(blank=True, default=list)),
                ("affiliate_tag_env_key", models.CharField(blank=True, default="", max_length=120)),
                ("disclosure", models.CharField(blank=True, default="", max_length=500)),
                ("notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="StorefrontClick",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("module", models.CharField(default="DIRECT_STOREFRONT", max_length=40)),
                ("need_reference", models.CharField(blank=True, default="", max_length=120)),
                ("project_reference", models.CharField(blank=True, default="", max_length=120)),
                ("product_reference", models.CharField(blank=True, default="", max_length=180)),
                ("outbound_url", models.URLField(max_length=1500)),
                ("user_agent", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("business", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="storefront_clicks", to="user_accounts.business")),
                ("merchant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="clicks", to="platform_affiliates.storefrontmerchant")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="storefront_clicks", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="StorefrontEarning",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("module", models.CharField(default="DIRECT_STOREFRONT", max_length=40)),
                ("external_order_reference", models.CharField(blank=True, default="", max_length=255)),
                ("gross_sales_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("commission_amount", models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("APPROVED", "Approved"), ("PAID", "Paid"), ("REVERSED", "Reversed")], default="PENDING", max_length=20)),
                ("occurred_on", models.DateField(default=django.utils.timezone.localdate)),
                ("reported_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("click", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="earnings", to="platform_affiliates.storefrontclick")),
                ("merchant", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="earnings", to="platform_affiliates.storefrontmerchant")),
            ],
            options={"ordering": ["-occurred_on", "-created_at"]},
        ),
        migrations.AddIndex(model_name="storefrontclick", index=models.Index(fields=["merchant", "created_at"], name="store_click_merchant_idx")),
        migrations.AddIndex(model_name="storefrontclick", index=models.Index(fields=["module", "created_at"], name="store_click_module_idx")),
        migrations.AddIndex(model_name="storefrontearning", index=models.Index(fields=["merchant", "status"], name="store_earn_merchant_idx")),
        migrations.AddIndex(model_name="storefrontearning", index=models.Index(fields=["module", "occurred_on"], name="store_earn_module_idx")),
        migrations.AddConstraint(
            model_name="storefrontearning",
            constraint=models.UniqueConstraint(condition=~models.Q(external_order_reference=""), fields=("merchant", "external_order_reference"), name="store_earning_order_unique"),
        ),
        migrations.RunPython(seed_amazon_merchant, migrations.RunPython.noop),
    ]
