from __future__ import annotations

import os

from rest_framework import serializers

from user_accounts.models import ServiceCategory
from user_accounts.models.business import Business, BusinessMember, BusinessCategory


MAX_LOGO_UPLOAD_MB = 5
ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
ALLOWED_LOGO_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/svg+xml",
}


class BusinessCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessCategory
        fields = ["id", "name", "created_at"]
        read_only_fields = ["id", "created_at"]


class BusinessSerializer(serializers.ModelSerializer):
    services_offered = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=ServiceCategory.objects.filter(is_active=True),
        required=False,
    )

    # IMPORTANT:
    # Business.logo is a models.FileField, not ImageField.
    # Use FileField here and validate size/type manually.
    logo = serializers.FileField(required=False, allow_null=True)

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
            "service_areas",
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
            logo = getattr(obj, "logo", None)
            if not logo:
                return None

            request = self.context.get("request")
            if request is not None:
                return request.build_absolute_uri(logo.url)

            return logo.url
        except Exception:
            return None

    def get_effective_service_radius_miles(self, obj):
        if getattr(obj, "is_online_only", False):
            return None
        if getattr(obj, "business_presence_mode", "") == Business.PRESENCE_ONLINE:
            return None
        return obj.service_radius_miles

    def validate_logo(self, file_obj):
        if not file_obj:
            return file_obj

        size = int(getattr(file_obj, "size", 0) or 0)
        max_bytes = MAX_LOGO_UPLOAD_MB * 1024 * 1024

        if size > max_bytes:
            raise serializers.ValidationError(
                f"Logo must be {MAX_LOGO_UPLOAD_MB}MB or smaller."
            )

        filename = str(getattr(file_obj, "name", "") or "").strip()
        _, ext = os.path.splitext(filename.lower())

        if ext and ext not in ALLOWED_LOGO_EXTENSIONS:
            raise serializers.ValidationError(
                "Logo must be a PNG, JPG, JPEG, WEBP, or SVG file."
            )

        content_type = str(getattr(file_obj, "content_type", "") or "").lower()

        if content_type and content_type not in ALLOWED_LOGO_CONTENT_TYPES:
            raise serializers.ValidationError(
                "Logo must be a PNG, JPG, JPEG, WEBP, or SVG file."
            )

        return file_obj

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
            raise serializers.ValidationError(
                "service_radius_miles must be between 1 and 500."
            )

        return v

    def validate_service_areas(self, value):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("service_areas must be a list.")
        if len(value) > 100:
            raise serializers.ValidationError("A business may store up to 100 service areas.")

        allowed_types = {"ZIP", "CITY", "COUNTY", "STATE", "REGION", "NATIONWIDE"}
        allowed_scopes = {"BOTH", "RESIDENTIAL", "COMMERCIAL"}
        cleaned = []

        for index, raw in enumerate(value):
            if not isinstance(raw, dict):
                raise serializers.ValidationError(f"service_areas[{index}] must be an object.")

            area_type = str(raw.get("area_type") or "ZIP").strip().upper()
            project_scope = str(raw.get("project_scope") or "BOTH").strip().upper()

            if area_type not in allowed_types:
                raise serializers.ValidationError(f"service_areas[{index}].area_type is invalid.")
            if project_scope not in allowed_scopes:
                raise serializers.ValidationError(f"service_areas[{index}].project_scope is invalid.")

            values = raw.get("values") or []
            if not isinstance(values, list):
                raise serializers.ValidationError(f"service_areas[{index}].values must be a list.")

            values = [str(item or "").strip()[:120] for item in values if str(item or "").strip()]
            if area_type == "NATIONWIDE":
                values = ["US"]
            elif not values:
                raise serializers.ValidationError(f"service_areas[{index}] requires at least one location.")

            minimum = raw.get("minimum_project_amount", "")
            if minimum not in (None, ""):
                try:
                    minimum = str(max(0, int(float(minimum))))
                except Exception:
                    raise serializers.ValidationError(
                        f"service_areas[{index}].minimum_project_amount must be a number."
                    )
            else:
                minimum = ""

            cleaned.append({
                "id": str(raw.get("id") or f"area-{index + 1}")[:100],
                "name": str(raw.get("name") or "").strip()[:160],
                "area_type": area_type,
                "values": values[:500],
                "project_scope": project_scope,
                "minimum_project_amount": minimum,
                "notes": str(raw.get("notes") or "").strip()[:500],
                "active": raw.get("active") is not False,
            })

        return cleaned

    def validate_expected_gross_monthly(self, v):
        if v in (None, ""):
            return v

        try:
            if v < 0:
                raise serializers.ValidationError(
                    "expected_gross_monthly must be greater than or equal to 0."
                )
        except TypeError:
            raise serializers.ValidationError("expected_gross_monthly must be a number.")

        return v

    def validate(self, attrs):
        incoming_mode = attrs.get(
            "business_presence_mode",
            getattr(self.instance, "business_presence_mode", ""),
        )
        incoming_online_only = attrs.get(
            "is_online_only",
            getattr(self.instance, "is_online_only", False),
        )

        if incoming_mode == Business.PRESENCE_ONLINE:
            attrs["is_online_only"] = True
        elif "business_presence_mode" in attrs and incoming_online_only is True:
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