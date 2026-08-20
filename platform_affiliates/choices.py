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
    MARKETPLACE_FEE = "MARKETPLACE_FEE", "Marketplace 1% Fee"
    BUSINESS_PLATFORM_FEE = "BUSINESS_PLATFORM_FEE", "Business Platform Fee"
    PLATFORM_FEE = "PLATFORM_FEE", "Legacy Platform Fee"
    SBO_SUBSCRIPTION = "SBO_SUBSCRIPTION", "Business Subscription"
    GROWTH_OS_SUBSCRIPTION = "GROWTH_OS_SUBSCRIPTION", "Social Media Subscription"
    HEALTH_SUBSCRIPTION = "HEALTH_SUBSCRIPTION", "Health Subscription"
    HEALTH_AI_SUBSCRIPTION = "HEALTH_AI_SUBSCRIPTION", "Health AI Subscription"
    FINANCE_SUBSCRIPTION = "FINANCE_SUBSCRIPTION", "Finance Subscription"
    PERSONAL_SUBSCRIPTION = "PERSONAL_SUBSCRIPTION", "Personal Subscription / Add-on"
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
