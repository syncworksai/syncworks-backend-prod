from __future__ import annotations

from rest_framework import serializers

from user_accounts.models import PartnerWorkTicket


class PartnerWorkTicketSerializer(serializers.ModelSerializer):
    source_ticket_code = serializers.CharField(
        source="source_ticket.ticket_code",
        read_only=True,
    )
    source_project_id = serializers.IntegerField(
        source="source_ticket.project_id",
        read_only=True,
        allow_null=True,
    )
    hiring_business_name = serializers.CharField(
        source="hiring_business.name",
        read_only=True,
    )
    partner_business_name = serializers.CharField(
        source="partner_business.name",
        read_only=True,
    )
    assigned_member_name = serializers.SerializerMethodField()
    partner_internal_cost_cents = serializers.SerializerMethodField()
    partner_internal_notes = serializers.SerializerMethodField()
    hiring_business_notes = serializers.SerializerMethodField()

    class Meta:
        model = PartnerWorkTicket
        fields = [
            "id",
            "relationship",
            "source_ticket",
            "source_ticket_code",
            "source_project_id",
            "hiring_business",
            "hiring_business_name",
            "partner_business",
            "partner_business_name",
            "assigned_member",
            "assigned_member_name",
            "title",
            "scope",
            "status",
            "service_address",
            "service_zip",
            "access_instructions",
            "share_customer_contact",
            "customer_contact_name",
            "customer_contact_email",
            "customer_contact_phone",
            "agreed_amount_cents",
            "partner_internal_cost_cents",
            "partner_internal_notes",
            "hiring_business_notes",
            "shared_updates",
            "completion_summary",
            "blocked_reason",
            "offered_by",
            "accepted_by",
            "reviewed_by",
            "offered_at",
            "accepted_at",
            "declined_at",
            "scheduled_at",
            "started_at",
            "submitted_at",
            "completed_at",
            "cancelled_at",
            "updated_at",
        ]
        read_only_fields = fields

    def _active_business_id(self):
        return self.context.get("active_business_id")

    def get_assigned_member_name(self, obj) -> str:
        user = obj.assigned_member
        if not user:
            return ""
        return user.get_full_name() or user.email or f"User #{user.id}"

    def get_partner_internal_cost_cents(self, obj):
        if self._active_business_id() == obj.partner_business_id:
            return obj.partner_internal_cost_cents
        return None

    def get_partner_internal_notes(self, obj):
        if self._active_business_id() == obj.partner_business_id:
            return obj.partner_internal_notes
        return None

    def get_hiring_business_notes(self, obj):
        if self._active_business_id() == obj.hiring_business_id:
            return obj.hiring_business_notes
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not instance.share_customer_contact:
            data["customer_contact_name"] = ""
            data["customer_contact_email"] = ""
            data["customer_contact_phone"] = ""
        return data
