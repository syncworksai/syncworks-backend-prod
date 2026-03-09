# user_accounts/models/kpis.py
from __future__ import annotations

from django.db import models
from django.utils import timezone


class PlatformDailyKpi(models.Model):
    """
    Daily snapshot across the entire platform (God Mode).
    """
    day = models.DateField(db_index=True, unique=True)

    # Growth
    signups = models.IntegerField(default=0)
    businesses_created = models.IntegerField(default=0)
    active_businesses_30d = models.IntegerField(default=0)

    # Marketplace demand/supply
    marketplace_tickets_created = models.IntegerField(default=0)
    marketplace_tickets_accepted = models.IntegerField(default=0)
    marketplace_fill_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)  # 0..1

    # Ops
    tickets_created = models.IntegerField(default=0)
    tickets_completed = models.IntegerField(default=0)
    tickets_cancelled = models.IntegerField(default=0)
    open_backlog = models.IntegerField(default=0)

    # Financial (from invoices)
    gmv = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    platform_fee_collected = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    platform_fee_due = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cash_gmv = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-day"]


class BusinessDailyKpi(models.Model):
    """
    Daily snapshot per business (SBO dashboard).
    """
    day = models.DateField(db_index=True)
    business_id = models.IntegerField(db_index=True)

    # Demand/supply
    tickets_created = models.IntegerField(default=0)
    tickets_assigned = models.IntegerField(default=0)
    tickets_accepted = models.IntegerField(default=0)
    tickets_completed = models.IntegerField(default=0)
    tickets_cancelled = models.IntegerField(default=0)
    open_backlog = models.IntegerField(default=0)

    # Financial
    gmv = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cash_gmv = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    platform_fee_collected = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    platform_fee_due = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("day", "business_id")
        ordering = ["-day"]
        indexes = [
            models.Index(fields=["business_id", "day"]),
        ]


class MarketplaceCellDailyKpi(models.Model):
    """
    Daily marketplace liquidity by (category_id, zip_prefix).
    This tells you where demand exists without supply.
    """
    day = models.DateField(db_index=True)
    category_id = models.IntegerField(db_index=True)
    zip_prefix = models.CharField(max_length=5, db_index=True)  # e.g. first 3 digits "303"

    tickets_created = models.IntegerField(default=0)
    tickets_accepted = models.IntegerField(default=0)
    fill_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("day", "category_id", "zip_prefix")
        ordering = ["-day"]
        indexes = [
            models.Index(fields=["day", "category_id"]),
            models.Index(fields=["day", "zip_prefix"]),
        ]
