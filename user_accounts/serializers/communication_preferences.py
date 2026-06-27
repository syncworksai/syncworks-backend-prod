from __future__ import annotations

from rest_framework import serializers

from user_accounts.models import CommunicationPreference


class CommunicationPreferenceSerializer(serializers.ModelSerializer):
    sms_ready = serializers.BooleanField(read_only=True)
    sms_upgrade_required = serializers.SerializerMethodField()
    inbox_identity = serializers.SerializerMethodField()
    automation_summary = serializers.SerializerMethodField()

    class Meta:
        model = CommunicationPreference
        fields = [
            "id", "user", "business", "scope",
            "internal_inbox_enabled",
            "email_notifications_enabled",
            "push_notifications_enabled",
            "sms_notifications_enabled",
            "sms_paid_addon_active",
            "sms_consent_confirmed",
            "sms_phone_verified",
            "sms_ready",
            "sms_upgrade_required",
            "automatic_updates_enabled",
            "assignment_mode",
            "owner_oversight_enabled",
            "urgent_unread_escalation_enabled",
            "email_digest_for_low_priority",
            "quiet_hours_enabled",
            "quiet_hours_start",
            "quiet_hours_end",
            "emergency_override_enabled",
            "timezone",
            "inbox_identity",
            "automation_summary",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "user", "business", "scope",
            "sms_paid_addon_active",
            "sms_consent_confirmed",
            "sms_phone_verified",
            "sms_ready",
            "sms_upgrade_required",
            "inbox_identity",
            "automation_summary",
            "created_at",
            "updated_at",
        ]

    def get_sms_upgrade_required(self, obj):
        return not bool(obj.sms_paid_addon_active)

    def get_inbox_identity(self, obj):
        if obj.scope == CommunicationPreference.Scope.PERSONAL:
            return {
                "key": "personal",
                "label": "Personal Inbox",
                "ownership": "USER",
                "description": "Private personal requests, payments, modules, and social connections.",
            }
        if obj.scope == CommunicationPreference.Scope.PROPERTY_MANAGEMENT:
            return {
                "key": f"property-management-{obj.business_id or 'default'}",
                "label": "Property Management Inbox",
                "ownership": "BUSINESS",
                "description": "Property, tenant, investor, vendor, and work-order conversations.",
            }
        return {
            "key": f"business-{obj.business_id or 'default'}",
            "label": "Business Inbox",
            "ownership": "BUSINESS",
            "description": "Customer, ticket, lead, quote, invoice, and team conversations.",
        }

    def get_automation_summary(self, obj):
        return {
            "primary_channel": "INTERNAL_INBOX",
            "email_fallback": bool(obj.email_notifications_enabled),
            "sms_available": bool(obj.sms_ready),
            "automatic_routing": obj.assignment_mode == CommunicationPreference.AssignmentMode.AUTO,
            "owner_oversight": bool(obj.owner_oversight_enabled),
            "quiet_hours": bool(obj.quiet_hours_enabled),
            "urgent_escalation": bool(obj.urgent_unread_escalation_enabled),
        }

    def validate(self, attrs):
        instance = self.instance
        requested_sms = attrs.get(
            "sms_notifications_enabled",
            getattr(instance, "sms_notifications_enabled", False),
        )
        if requested_sms:
            if not getattr(instance, "sms_paid_addon_active", False):
                raise serializers.ValidationError({
                    "sms_notifications_enabled": "Activate the paid SMS add-on before enabling SMS alerts."
                })
            if not (
                getattr(instance, "sms_consent_confirmed", False)
                and getattr(instance, "sms_phone_verified", False)
            ):
                raise serializers.ValidationError({
                    "sms_notifications_enabled": "SMS consent and phone verification are required."
                })
        return attrs
