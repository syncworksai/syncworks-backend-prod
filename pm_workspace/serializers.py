from rest_framework import serializers

from .models import PMTenant, PMTenantInvitation, PMWorkspace


class PMWorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMWorkspace
        fields = "__all__"
        read_only_fields = ("id", "owner", "created_at", "updated_at")


class PMTenantSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    latest_invitation = serializers.SerializerMethodField()

    class Meta:
        model = PMTenant
        fields = "__all__"
        read_only_fields = ("id", "workspace", "user", "status", "created_by", "created_at", "updated_at")

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    def get_latest_invitation(self, obj):
        invite = obj.invitations.order_by("-created_at").first()
        if not invite:
            return None
        return {
            "id": invite.id,
            "status": invite.status,
            "mode": invite.mode,
            "expires_at": invite.expires_at,
            "sent_at": invite.sent_at,
            "sent_to_email": invite.sent_to_email,
        }


class PMTenantInvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMTenantInvitation
        fields = (
            "id", "tenant", "mode", "status", "code", "expires_at", "sent_to_email",
            "sent_from_name", "reply_to_email", "sent_at", "accepted_at", "revoked_at", "created_at"
        )
        read_only_fields = fields
