# backend/user_accounts/migrations/0044_businessaccesscontrol.py
from __future__ import annotations

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("user_accounts", "0043_platformbillingprofile_card_brand_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="BusinessAccessControl",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_locked", models.BooleanField(default=False)),
                ("lock_reason", models.CharField(choices=[("CARD_EXPIRED", "Card Expired"), ("FAILED_PAYMENT", "Failed Payment"), ("MANUAL", "Manual"), ("OTHER", "Other")], default="OTHER", max_length=32)),
                ("locked_at", models.DateTimeField(blank=True, null=True)),
                ("last_unlock_requested_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("business", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="access_control", to="user_accounts.business")),
                ("locked_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="business_locks_created", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
