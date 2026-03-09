# backend/user_accounts/migrations/0049_salespipeline_add_business.py
from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):
    """
    Fix for:
      OperationalError: no such column: user_accounts_salespipeline.business_id

    Adds SalesPipeline.business (scoping pipelines to X-Business-Id).
    """

    dependencies = [
        ("user_accounts", "0048_prospectactivity_occurred_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="salespipeline",
            name="business",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sales_pipelines",
                to="user_accounts.business",
            ),
        ),

        # ✅ Optional but strongly recommended:
        # If your SalesPipeline model/viewset expects created_by, add it safely.
        migrations.AddField(
            model_name="salespipeline",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="sales_pipelines_created",
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # ✅ Optional description field if your serializer/model expects it.
        migrations.AddField(
            model_name="salespipeline",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
    ]