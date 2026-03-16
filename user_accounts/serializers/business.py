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
    services_offered = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=ServiceCategory.objects.all(),
        required=False,
    )

    logo_url = serializers.SerializerMethodField()
    effective_service_radius_miles = serializers.SerializerMethodField()

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

            "headline",
            "services_text",
            "address",
            "city",
            "state",
            "website",

            "business_presence_mode",
            "is_online_only",

            "facebook_url",
            "instagram_url",
            "linkedin_url",
            "google_business_url",
            "youtube_url",
            "tiktok_url",

            "business_card_code",

            "accepts_marketplace_tickets",
            "base_zip",
            "service_radius_miles",
            "effective_service_radius_miles",
            "services_offered",

            "expected_gross_monthly",
            "is_licensed",
            "is_insured",
            "is_bonded",
            "background_checked",
            "emergency_service",

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
            "business_card_code",
            "effective_service_radius_miles",
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

    def get_effective_service_radius_miles(self, obj):
        if getattr(obj, "is_online_only", False):
            return None
        if getattr(obj, "business_presence_mode", "") == Business.PRESENCE_ONLINE:
            return None
        return obj.service_radius_miles

    def validate_state(self, v):
        v = (v or "").strip().upper()
        if v and len(v) != 2:
            raise serializers.ValidationError("State must be 2 letters (example: AL).")
        return v

    def validate_base_zip(self, v):
        v = (v or "").strip()
        digits = "".join([c for c in v if c.isdigit()])
        return digits[:5] if digits else ""

    def _normalize_url(self, v):
        v = (v or "").strip()
        if not v:
            return ""
        if not (v.startswith("http://") or v.startswith("https://")):
            v = f"https://{v}"
        return v

    def validate_website(self, v):
        return self._normalize_url(v)

    def validate_facebook_url(self, v):
        return self._normalize_url(v)

    def validate_instagram_url(self, v):
        return self._normalize_url(v)

    def validate_linkedin_url(self, v):
        return self._normalize_url(v)

    def validate_google_business_url(self, v):
        return self._normalize_url(v)

    def validate_youtube_url(self, v):
        return self._normalize_url(v)

    def validate_tiktok_url(self, v):
        return self._normalize_url(v)

    def validate_business_presence_mode(self, v):
        v = (v or "").strip()
        if not v:
            return ""
        allowed = {x[0] for x in Business.BUSINESS_PRESENCE_CHOICES}
        if v not in allowed:
            raise serializers.ValidationError("Invalid business presence mode.")
        return v

    def validate_service_radius_miles(self, v):
        if v is None:
            return v
        try:
            v = int(v)
        except Exception:
            raise serializers.ValidationError("service_radius_miles must be an integer.")
        if v < 1 or v > 500:
            raise serializers.ValidationError("service_radius_miles must be between 1 and 500.")
        return v

    def validate(self, attrs):
        incoming_mode = attrs.get(
            "business_presence_mode",
            getattr(self.instance, "business_presence_mode", "")
        )
        incoming_online_only = attrs.get(
            "is_online_only",
            getattr(self.instance, "is_online_only", False)
        )

        if incoming_mode == Business.PRESENCE_ONLINE:
            attrs["is_online_only"] = True
        elif "business_presence_mode" in attrs and incoming_online_only is True:
            # keep explicit online-only only if user intentionally sent it;
            # otherwise normalize non-online modes back to False
            attrs["is_online_only"] = bool(attrs.get("is_online_only", False))

        return attrs

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