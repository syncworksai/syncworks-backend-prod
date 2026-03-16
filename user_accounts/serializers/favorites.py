from __future__ import annotations

from rest_framework import serializers

from user_accounts.models import FavoriteBusiness, Business


class BusinessMiniSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()
    display_location = serializers.SerializerMethodField()
    services_offered = serializers.SerializerMethodField()
    effective_service_radius_miles = serializers.SerializerMethodField()

    class Meta:
        model = Business
        fields = [
            "id",
            "name",
            "logo_url",
            "headline",
            "services_text",
            "phone",
            "business_email",
            "address",
            "city",
            "state",
            "display_location",
            "website",

            "business_presence_mode",
            "is_online_only",

            "facebook_url",
            "instagram_url",
            "linkedin_url",
            "google_business_url",
            "youtube_url",
            "tiktok_url",

            "base_zip",
            "service_radius_miles",
            "effective_service_radius_miles",
            "accepts_marketplace_tickets",
            "business_card_code",
            "is_licensed",
            "is_insured",
            "is_bonded",
            "background_checked",
            "emergency_service",
            "services_offered",
        ]
        read_only_fields = fields

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

    def get_display_location(self, obj):
        city = (getattr(obj, "city", "") or "").strip()
        state = (getattr(obj, "state", "") or "").strip()
        if city and state:
            return f"{city}, {state}"
        return city or state or ""

    def get_services_offered(self, obj):
        try:
            out = []
            for cat in obj.services_offered.all().order_by("name"):
                out.append(
                    {
                        "id": cat.id,
                        "name": getattr(cat, "name", "") or "",
                        "key": getattr(cat, "key", "") or "",
                        "path": getattr(cat, "path", "") or "",
                    }
                )
            return out
        except Exception:
            return []

    def get_effective_service_radius_miles(self, obj):
        try:
            if hasattr(obj, "effective_service_radius_miles"):
                value = obj.effective_service_radius_miles()
                return value
        except Exception:
            pass

        try:
            if getattr(obj, "is_online_only", False):
                return None
            if getattr(obj, "business_presence_mode", "") == getattr(Business, "PRESENCE_ONLINE", "online"):
                return None
            return getattr(obj, "service_radius_miles", None)
        except Exception:
            return getattr(obj, "service_radius_miles", None)


class FavoriteBusinessSerializer(serializers.ModelSerializer):
    business = serializers.SerializerMethodField()
    business_id = serializers.PrimaryKeyRelatedField(
        source="business",
        queryset=Business.objects.all(),
        write_only=True,
    )

    class Meta:
        model = FavoriteBusiness
        fields = [
            "id",
            "customer",
            "business",
            "business_id",
            "nickname",
            "last_used_at",
            "created_at",
        ]
        read_only_fields = ["id", "customer", "business", "last_used_at", "created_at"]

    def get_business(self, obj):
        return BusinessMiniSerializer(
            obj.business,
            context=self.context,
        ).data


class FavoriteBusinessClaimSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=64)
    nickname = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")