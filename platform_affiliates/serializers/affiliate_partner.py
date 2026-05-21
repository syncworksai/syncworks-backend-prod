from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers

from platform_affiliates.choices import PayoutProvider
from platform_affiliates.models import AffiliatePartner
from platform_affiliates.services.agreement_service import record_agreement_acceptance
from platform_affiliates.services.code_generator import (
    generate_affiliate_code,
    normalize_affiliate_code,
)
from platform_affiliates.services.qr_service import (
    build_qr_svg_placeholder,
    build_referral_link,
)


class AffiliatePartnerListSerializer(serializers.ModelSerializer):
    referred_business_count = serializers.IntegerField(read_only=True, default=0)
    active_business_count = serializers.IntegerField(read_only=True, default=0)
    referral_link = serializers.SerializerMethodField()

    class Meta:
        model = AffiliatePartner
        fields = [
            "id",
            "name",
            "email",
            "phone",
            "code",
            "status",
            "payout_provider",
            "referred_business_count",
            "active_business_count",
            "referral_link",
            "created_at",
            "updated_at",
        ]

    def get_referral_link(self, obj):
        return build_referral_link(obj.code)


class AffiliatePartnerDetailSerializer(serializers.ModelSerializer):
    referral_link = serializers.SerializerMethodField()
    qr_code_svg = serializers.SerializerMethodField()

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
            "agreement_accepted_ip",
            "agreement_accepted_user_agent",
            "notes",
            "approved_by",
            "approved_at",
            "referral_link",
            "qr_code_svg",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "code",
            "agreement_accepted_at",
            "agreement_accepted_ip",
            "agreement_accepted_user_agent",
            "approved_by",
            "approved_at",
            "created_at",
            "updated_at",
        ]

    def get_referral_link(self, obj):
        return build_referral_link(obj.code)

    def get_qr_code_svg(self, obj):
        return build_qr_svg_placeholder(obj.code)


class AffiliateApplicationSerializer(serializers.ModelSerializer):
    accepted_agreement = serializers.BooleanField(write_only=True)
    code = serializers.CharField(required=False, allow_blank=True)

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
            "payout_provider",
            "payout_email",
            "payout_notes",
            "application_notes",
            "referral_strategy",
            "accepted_agreement",
            "code",
        ]

    def validate_accepted_agreement(self, value):
        if value is not True:
            raise serializers.ValidationError("You must accept the affiliate agreement to apply.")
        return value

    def validate_payout_provider(self, value):
        return value or PayoutProvider.MANUAL

    def create(self, validated_data):
        request = self.context["request"]

        accepted_agreement = validated_data.pop("accepted_agreement")
        requested_code = normalize_affiliate_code(validated_data.pop("code", ""))

        if AffiliatePartner.objects.filter(user=request.user).exists():
            raise serializers.ValidationError("This user already has an affiliate application.")

        code = requested_code or generate_affiliate_code()

        if AffiliatePartner.objects.filter(code=code).exists():
            raise serializers.ValidationError({"code": "This affiliate code is already taken."})

        affiliate = AffiliatePartner.objects.create(
            user=request.user,
            code=code,
            agreement_accepted_at=timezone.now() if accepted_agreement else None,
            agreement_accepted_ip=self.context.get("ip_address"),
            agreement_accepted_user_agent=self.context.get("user_agent", ""),
            **validated_data,
        )

        record_agreement_acceptance(
            affiliate=affiliate,
            user=request.user,
            ip_address=self.context.get("ip_address"),
            user_agent=self.context.get("user_agent", ""),
        )

        return affiliate