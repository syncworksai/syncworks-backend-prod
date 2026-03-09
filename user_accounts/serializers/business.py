# user_accounts/serializers/business.py
from __future__ import annotations

from rest_framework import serializers
from user_accounts.models import ServiceCategory
from user_accounts.models.business import Business, BusinessMember, BusinessCategory


class BusinessCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessCategory
        fields = ["id", "name", "created_at"]
        read_only_fields = ["id", "created_at"]


class BusinessSerializer(serializers.ModelSerializer):
    # ✅ This is the canonical marketplace matching list
    # Frontend PATCH sends: { services_offered: [leafCategoryIds...] }
    services_offered = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=ServiceCategory.objects.all(),
        required=False,
    )

    # logo upload is handled via "logo" FileField in multipart
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Business
        fields = [
            "id",
            "name",
            "owner",
            "is_active",
            "created_at",

            "business_email",
            "owner_name",
            "phone",

            "logo",
            "logo_url",

            # Business Card profile fields
            "headline",
            "services_text",
            "address",
            "city",
            "state",
            "website",
            "business_card_code",

            # Marketplace discovery fields
            "accepts_marketplace_tickets",
            "base_zip",
            "service_radius_miles",
            "services_offered",

            # ✅ NEW: business ops + compliance
            "expected_gross_monthly",
            "is_licensed",
            "is_insured",
            "is_bonded",
            "background_checked",
            "emergency_service",

            # Billing
            "billing_exempt",
            "billing_exempt_reason",
            "billing_exempt_until",
        ]
        read_only_fields = [
            "id",
            "owner",
            "created_at",
            "billing_exempt",
            "billing_exempt_reason",
            "billing_exempt_until",
            "logo_url",
            # code is system-managed (generated in model.save)
            "business_card_code",
        ]

    def get_logo_url(self, obj):
        try:
            if not obj.logo:
                return None
            request = self.context.get("request")
            if request is not None:
                return request.build_absolute_uri(obj.logo.url)
            return obj.logo.url
        except Exception:
            return None

    def validate_state(self, v):
        v = (v or "").strip().upper()
        if v and len(v) != 2:
            raise serializers.ValidationError("State must be 2 letters (example: AL).")
        return v

    def validate_base_zip(self, v):
        v = (v or "").strip()
        digits = "".join([c for c in v if c.isdigit()])
        return digits[:5] if digits else ""

    def validate_service_radius_miles(self, v):
        if v is None:
            return v
        try:
            v = int(v)
        except Exception:
            raise serializers.ValidationError("service_radius_miles must be an integer.")
        if v < 1 or v > 200:
            raise serializers.ValidationError("service_radius_miles must be between 1 and 200.")
        return v

    def create(self, validated_data):
        services = validated_data.pop("services_offered", [])
        business = super().create(validated_data)
        if services is not None:
            business.services_offered.set(services)
        return business

    def update(self, instance, validated_data):
        services = validated_data.pop("services_offered", None)
        instance = super().update(instance, validated_data)
        if services is not None:
            instance.services_offered.set(services)
        return instance


class BusinessMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessMember
        fields = [
            "id",
            "business",
            "user",
            "role",
            "is_active",
            "can_manage_team",
            "can_manage_settings",
            "can_view_financials",
            "can_manage_invoices",
            "can_create_tickets",
            "can_assign_tickets",
            "can_close_tickets",
            "can_manage_schedule",
            "can_manage_categories",
            "can_manage_properties",
            "can_manage_connections",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]