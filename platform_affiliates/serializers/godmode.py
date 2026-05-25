from __future__ import annotations

from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from platform_affiliates.choices import (
    AffiliateStatus,
    CommissionStatus,
    PayoutBatchStatus,
)
from platform_affiliates.models import (
    AffiliateCommissionLedger,
    AffiliatePartner,
    AffiliatePayoutBatch,
    ReferralAttribution,
)
from platform_affiliates.serializers.commission_ledger import (
    AffiliateCommissionLedgerSerializer,
)
from platform_affiliates.serializers.payout_batch import (
    AffiliatePayoutBatchSerializer,
)
from platform_affiliates.serializers.referral_attribution import (
    ReferralAttributionSerializer,
)
from platform_affiliates.services.code_generator import (
    generate_affiliate_code,
    normalize_affiliate_code,
)
from user_accounts.models import Business


class GodModeAffiliateCreateSerializer(serializers.ModelSerializer):
    code = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = AffiliatePartner
        fields = [
            "id",
            "user",
            "name",
            "email",
            "phone",
            "address_line_1",
            "address_line_2",
            "city",
            "state",
            "zip_code",
            "code",
            "status",
            "commission_rate_bps",
            "payout_provider",
            "payout_email",
            "payout_notes",
            "external_payout_reference",
            "application_notes",
            "referral_strategy",
            "notes",
        ]

    def create(self, validated_data):
        requested_code = normalize_affiliate_code(validated_data.pop("code", ""))
        code = requested_code or generate_affiliate_code()

        if AffiliatePartner.objects.filter(code=code).exists():
            raise serializers.ValidationError({"code": "This affiliate code is already taken."})

        return AffiliatePartner.objects.create(code=code, **validated_data)


class GodModeAffiliateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AffiliatePartner
        fields = [
            "name",
            "email",
            "phone",
            "address_line_1",
            "address_line_2",
            "city",
            "state",
            "zip_code",
            "status",
            "commission_rate_bps",
            "payout_provider",
            "payout_email",
            "payout_notes",
            "external_payout_reference",
            "application_notes",
            "referral_strategy",
            "notes",
        ]

    def update(self, instance, validated_data):
        request = self.context.get("request")
        old_status = instance.status

        for key, value in validated_data.items():
            setattr(instance, key, value)

        if old_status != AffiliateStatus.ACTIVE and instance.status == AffiliateStatus.ACTIVE:
            instance.approved_by = request.user if request and request.user.is_authenticated else None
            instance.approved_at = timezone.now()

        instance.save()
        return instance


class GodModeAssignBusinessSerializer(serializers.Serializer):
    business_id = serializers.IntegerField()
    affiliate_id = serializers.IntegerField()
    reason = serializers.CharField(required=False, allow_blank=True)
    effective_from = serializers.DateField(required=False)
    retroactive = serializers.BooleanField(required=False, default=False)

    def validate_business_id(self, value):
        if not Business.objects.filter(id=value).exists():
            raise serializers.ValidationError("Business not found.")
        return value

    def validate_affiliate_id(self, value):
        if not AffiliatePartner.objects.filter(id=value).exists():
            raise serializers.ValidationError("Affiliate not found.")
        return value


class GodModeAffiliateOpsDetailSerializer(serializers.ModelSerializer):
    businesses = serializers.SerializerMethodField()
    recent_commissions = serializers.SerializerMethodField()
    payout_batches = serializers.SerializerMethodField()
    ops_metrics = serializers.SerializerMethodField()

    class Meta:
        model = AffiliatePartner
        fields = [
            "id",
            "user",
            "name",
            "email",
            "phone",
            "address_line_1",
            "address_line_2",
            "city",
            "state",
            "zip_code",
            "code",
            "status",
            "commission_rate_bps",
            "payout_provider",
            "payout_email",
            "payout_notes",
            "external_payout_reference",
            "application_notes",
            "referral_strategy",
            "agreement_version",
            "agreement_accepted_at",
            "approved_by",
            "approved_at",
            "notes",
            "created_at",
            "updated_at",
            "businesses",
            "recent_commissions",
            "payout_batches",
            "ops_metrics",
        ]

    def get_businesses(self, obj):
        qs = (
            ReferralAttribution.objects
            .select_related("business", "affiliate")
            .filter(affiliate=obj)
            .order_by("-created_at")[:50]
        )
        return ReferralAttributionSerializer(qs, many=True).data

    def get_recent_commissions(self, obj):
        qs = (
            AffiliateCommissionLedger.objects
            .select_related("business", "affiliate", "payout_batch")
            .filter(affiliate=obj)
            .order_by("-source_date", "-created_at")[:50]
        )
        return AffiliateCommissionLedgerSerializer(qs, many=True).data

    def get_payout_batches(self, obj):
        qs = (
            AffiliatePayoutBatch.objects
            .filter(affiliate=obj)
            .order_by("-period_end", "-created_at")[:24]
        )
        return AffiliatePayoutBatchSerializer(qs, many=True).data

    def get_ops_metrics(self, obj):
        ledger = AffiliateCommissionLedger.objects.filter(affiliate=obj)

        pending = ledger.filter(
            status__in=[
                CommissionStatus.PENDING,
                CommissionStatus.APPROVED,
            ]
        ).aggregate(total=Sum("commission_amount"))["total"] or 0

        paid = ledger.filter(
            status=CommissionStatus.PAID
        ).aggregate(total=Sum("commission_amount"))["total"] or 0

        lifetime = ledger.aggregate(
            total=Sum("commission_amount")
        )["total"] or 0

        syncworks_revenue = ledger.aggregate(
            total=Sum("net_syncworks_revenue_amount")
        )["total"] or 0

        open_payout_batches = AffiliatePayoutBatch.objects.filter(
            affiliate=obj,
            status__in=[
                PayoutBatchStatus.DRAFT,
                PayoutBatchStatus.PROCESSING,
            ],
        ).count()

        paid_batches = AffiliatePayoutBatch.objects.filter(
            affiliate=obj,
            status=PayoutBatchStatus.PAID,
        ).count()

        return {
            "pending_commission": str(pending),
            "paid_commission": str(paid),
            "lifetime_commission": str(lifetime),
            "syncworks_revenue_tracked": str(syncworks_revenue),
            "referred_business_count": ReferralAttribution.objects.filter(affiliate=obj).count(),
            "open_payout_batches": open_payout_batches,
            "paid_payout_batches": paid_batches,
        }