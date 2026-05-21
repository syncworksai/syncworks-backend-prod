from __future__ import annotations

from django.contrib import admin

from platform_affiliates.models import (
    AffiliateAgreementAcceptance,
    AffiliateAgreementTemplate,
    AffiliateAuditLog,
    AffiliateCommissionLedger,
    AffiliatePartner,
    AffiliatePayoutBatch,
    ReferralAttribution,
    ReferralClick,
)


@admin.register(AffiliatePartner)
class AffiliatePartnerAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "email", "status", "payout_provider", "created_at")
    search_fields = ("name", "email", "code")
    list_filter = ("status", "payout_provider", "created_at")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AffiliateAgreementTemplate)
class AffiliateAgreementTemplateAdmin(admin.ModelAdmin):
    list_display = ("title", "version", "is_active", "created_at")
    search_fields = ("title", "version")
    list_filter = ("is_active", "created_at")
    readonly_fields = ("created_at",)


@admin.register(AffiliateAgreementAcceptance)
class AffiliateAgreementAcceptanceAdmin(admin.ModelAdmin):
    list_display = ("affiliate", "agreement_version", "accepted_at", "ip_address")
    search_fields = ("affiliate__name", "affiliate__code", "agreement_version")
    list_filter = ("agreement_version", "accepted_at")
    readonly_fields = ("created_at",)


@admin.register(ReferralAttribution)
class ReferralAttributionAdmin(admin.ModelAdmin):
    list_display = ("business", "affiliate", "referral_code", "attribution_source", "effective_from", "retroactive")
    search_fields = ("business__name", "affiliate__name", "affiliate__code", "referral_code")
    list_filter = ("attribution_source", "retroactive", "created_at")
    readonly_fields = ("locked_at", "created_at", "updated_at")


@admin.register(ReferralClick)
class ReferralClickAdmin(admin.ModelAdmin):
    list_display = ("code", "affiliate", "ip_address", "landing_path", "created_at")
    search_fields = ("code", "affiliate__name", "affiliate__code", "landing_path")
    list_filter = ("created_at",)


@admin.register(AffiliateCommissionLedger)
class AffiliateCommissionLedgerAdmin(admin.ModelAdmin):
    list_display = (
        "affiliate",
        "business",
        "revenue_source",
        "net_syncworks_revenue_amount",
        "commission_amount",
        "status",
        "source_date",
    )
    search_fields = ("affiliate__name", "affiliate__code", "business__name", "source_reference")
    list_filter = ("revenue_source", "status", "source_date")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AffiliatePayoutBatch)
class AffiliatePayoutBatchAdmin(admin.ModelAdmin):
    list_display = ("affiliate", "period_start", "period_end", "total_amount", "status", "paid_at")
    search_fields = ("affiliate__name", "affiliate__code", "external_reference")
    list_filter = ("status", "period_start", "period_end")


@admin.register(AffiliateAuditLog)
class AffiliateAuditLogAdmin(admin.ModelAdmin):
    list_display = ("action", "actor", "affiliate", "business", "created_at")
    search_fields = ("action", "actor__email", "affiliate__name", "affiliate__code", "business__name")
    list_filter = ("action", "created_at")
    readonly_fields = ("created_at",)