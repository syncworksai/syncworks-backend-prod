from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers

from platform_affiliates.choices import AffiliateStatus
from platform_affiliates.models import AffiliatePartner
from platform_affiliates.services.code_generator import generate_affiliate_code, normalize_affiliate_code
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