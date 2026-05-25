from __future__ import annotations

from rest_framework import serializers

from platform_affiliates.models import AffiliatePartner, ReferralAttribution
from platform_affiliates.services.code_generator import normalize_affiliate_code
from user_accounts.models import Business, BusinessMember


def user_can_claim_for_business(user, business: Business) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False

    try:
        if business.owner_id == user.id:
            return True
    except Exception:
        pass

    try:
        return BusinessMember.objects.filter(
            business=business,
            user=user,
            is_active=True,
        ).exists()
    except Exception:
        return False


class ClaimAffiliateCodeSerializer(serializers.Serializer):
    business_id = serializers.IntegerField()
    code = serializers.CharField(max_length=32)

    def validate(self, attrs):
        request = self.context["request"]

        business_id = attrs.get("business_id")
        code = normalize_affiliate_code(attrs.get("code", ""))

        business = Business.objects.filter(id=business_id).first()
        if not business:
            raise serializers.ValidationError({"business_id": "Business not found."})

        if not user_can_claim_for_business(request.user, business):
            raise serializers.ValidationError({"business_id": "You cannot claim a code for this business."})

        if ReferralAttribution.objects.filter(business=business).exists():
            raise serializers.ValidationError({"business_id": "This business already has an affiliate attribution."})

        affiliate = AffiliatePartner.objects.filter(code=code, status="ACTIVE").first()
        if not affiliate:
            raise serializers.ValidationError({"code": "Affiliate code is invalid or inactive."})

        attrs["business"] = business
        attrs["affiliate"] = affiliate
        attrs["code"] = code

        return attrs