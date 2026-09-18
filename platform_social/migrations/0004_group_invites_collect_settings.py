import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("platform_social", "0003_groupmessage"),
    ]

    operations = [
        migrations.AlterField(
            model_name="groupmembership",
            name="status",
            field=models.CharField(
                choices=[
                    ("INVITED", "Invited"),
                    ("REQUESTED", "Requested"),
                    ("ACTIVE", "Active"),
                    ("DECLINED", "Declined"),
                    ("REMOVED", "Removed"),
                ],
                default="INVITED",
                max_length=12,
            ),
        ),
        migrations.CreateModel(
            name="GroupInviteLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("role", models.CharField(choices=[("OWNER", "Owner"), ("DIRECTOR", "Director"), ("MANAGER", "Manager / Coach"), ("MEMBER", "Member")], default="MEMBER", max_length=12)),
                ("is_active", models.BooleanField(default=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("max_uses", models.PositiveIntegerField(blank=True, null=True)),
                ("uses_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="social_group_invite_links_created", to=settings.AUTH_USER_MODEL)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="invite_links", to="platform_social.socialgroup")),
            ],
            options={
                "ordering": ("-created_at", "-id"),
                "indexes": [
                    models.Index(fields=["group", "is_active"], name="social_group_link_active"),
                    models.Index(fields=["token", "is_active"], name="social_group_link_token"),
                ],
            },
        ),
        migrations.CreateModel(
            name="GroupPaymentSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("cash_app_url", models.URLField(blank=True)),
                ("cash_app_label", models.CharField(blank=True, max_length=80)),
                ("venmo_url", models.URLField(blank=True)),
                ("venmo_label", models.CharField(blank=True, max_length=80)),
                ("zelle_instructions", models.CharField(blank=True, max_length=240)),
                ("stripe_payment_link", models.URLField(blank=True)),
                ("platform_fee_bps", models.PositiveSmallIntegerField(default=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("group", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="payment_settings", to="platform_social.socialgroup")),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="social_payment_settings_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name_plural": "Group payment settings"},
        ),
        migrations.CreateModel(
            name="CollectionPayment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("method", models.CharField(choices=[("STRIPE", "Stripe"), ("CASH_APP", "Cash App"), ("VENMO", "Venmo"), ("ZELLE", "Zelle"), ("OTHER", "Other")], max_length=12)),
                ("gross_amount_cents", models.PositiveIntegerField()),
                ("platform_fee_bps", models.PositiveSmallIntegerField(default=100)),
                ("platform_fee_cents", models.PositiveIntegerField(default=0)),
                ("fee_status", models.CharField(choices=[("PENDING", "Pending"), ("COLLECTED", "Collected"), ("WAIVED", "Waived")], default="PENDING", max_length=12)),
                ("external_reference", models.CharField(blank=True, max_length=180)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("collection", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payments", to="platform_social.collection")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="social_collection_payments_recorded", to=settings.AUTH_USER_MODEL)),
                ("payer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="social_collection_payments", to=settings.AUTH_USER_MODEL)),
                ("share", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="payments", to="platform_social.collectionshare")),
            ],
            options={
                "ordering": ("-created_at", "-id"),
                "indexes": [
                    models.Index(fields=["collection", "method", "created_at"], name="social_collect_payment"),
                    models.Index(fields=["fee_status", "created_at"], name="social_collect_fee_status"),
                ],
            },
        ),
    ]
