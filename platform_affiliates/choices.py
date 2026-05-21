from __future__ import annotations

from django.db import models


class AffiliateStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ACTIVE = "ACTIVE", "Active"
    SUSPENDED = "SUSPENDED", "Suspended"
    DEACTIVATED = "DEACTIVATED", "Deactivated"


class AttributionSource(models.TextChoices):
    LINK = "LINK", "Referral Link"
    MANUAL_CODE = "MANUAL_CODE", "Manual Code"
    GODMODE_MANUAL = "GODMODE_MANUAL", "God Mode Manual"


class RevenueSource(models.TextChoices):
    PLATFORM_FEE = "PLATFORM_FEE", "Platform Fee"
    SBO_SUBSCRIPTION = "SBO_SUBSCRIPTION", "SBO Subscription"
    GROWTH_OS_SUBSCRIPTION = "GROWTH_OS_SUBSCRIPTION", "Growth OS Subscription"
    OTHER_SYNCWORKS_REVENUE = "OTHER_SYNCWORKS_REVENUE", "Other SyncWorks Revenue"


class CommissionStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    PAID = "PAID", "Paid"
    VOID = "VOID", "Void"
    CLAWED_BACK = "CLAWED_BACK", "Clawed Back"


class PayoutBatchStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    APPROVED = "APPROVED", "Approved"
    PROCESSING = "PROCESSING", "Processing"
    PAID = "PAID", "Paid"
    FAILED = "FAILED", "Failed"


class PayoutProvider(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    STRIPE = "STRIPE", "Stripe"
    ACH = "ACH", "ACH"
    OTHER = "OTHER", "Other"