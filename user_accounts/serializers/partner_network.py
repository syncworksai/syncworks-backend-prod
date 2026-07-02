from __future__ import annotations

from rest_framework import serializers

from user_accounts.models import (
    Business,
    BusinessPartnerInvitation,
    BusinessPartnerRelationship,
)


class PartnerBusinessCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Business
        fields = [
            "id",
            "name",
            "business_email",
            "phone",
            "headline",
            "services_text",
            "city",
            "state",
            "base_zip",
            "is_licensed",
            "is_insured",
            "is_bonded",
            "background_checked",
        ]
        read_only_fields = fields


class BusinessPartnerRelationshipSerializer(serializers.ModelSerializer):
    hiring_business_card = PartnerBusinessCardSerializer(
        source="hiring_business",
        read_only=True,
    )
    partner_business_card = PartnerBusinessCardSerializer(
        source="partner_business",
        read_only=True,
    )
    services_allowed = serializers.PrimaryKeyRelatedField(
        many=True,
        read_only=True,
    )

    class Meta:
        model = BusinessPartnerRelationship
        fields = [
            "id",
            "hiring_business",
            "hiring_business_card",
            "partner_business",
            "partner_business_card",
            "relationship_type",
            "status",
            "preferred_partner",
            "services_allowed",
            "default_markup_type",
            "default_markup_value",
            "payment_terms_days",
            "insurance_verified",
            "license_verified",
            "compliance_notes",
            "internal_notes",
            "invited_by",
            "accepted_by",
            "accepted_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "hiring_business",
            "hiring_business_card",
            "partner_business",
            "partner_business_card",
            "status",
            "services_allowed",
            "invited_by",
            "accepted_by",
            "accepted_at",
            "created_at",
            "updated_at",
        ]


class BusinessPartnerInvitationSerializer(serializers.ModelSerializer):
    inviting_business_card = PartnerBusinessCardSerializer(
        source="inviting_business",
        read_only=True,
    )
    target_business_card = PartnerBusinessCardSerializer(
        source="target_business",
        read_only=True,
    )
    relationship_detail = BusinessPartnerRelationshipSerializer(
        source="relationship",
        read_only=True,
    )

    class Meta:
        model = BusinessPartnerInvitation
        fields = [
            "id",
            "inviting_business",
            "inviting_business_card",
            "target_business",
            "target_business_card",
            "relationship",
            "relationship_detail",
            "contact_name",
            "email",
            "phone",
            "business_name",
            "relationship_type",
            "message",
            "token",
            "status",
            "affiliate_code",
            "created_by",
            "created_at",
            "expires_at",
            "responded_at",
        ]
        read_only_fields = [
            "id",
            "inviting_business",
            "inviting_business_card",
            "relationship",
            "relationship_detail",
            "token",
            "status",
            "affiliate_code",
            "created_by",
            "created_at",
            "responded_at",
        ]
