from rest_framework import serializers

from .models import PMProject, PMProjectUpdate, PMProperty, PMTenant, PMTenantInvitation, PMWorkspace


class PMWorkspaceSerializer(serializers.ModelSerializer):
    is_free_portfolio = serializers.SerializerMethodField()
    additional_portfolio_price = serializers.SerializerMethodField()

    class Meta:
        model = PMWorkspace
        fields = "__all__"
        read_only_fields = ("id", "owner", "created_at", "updated_at", "is_free_portfolio", "additional_portfolio_price")

    def get_is_free_portfolio(self, obj):
        first_id = PMWorkspace.objects.filter(owner=obj.owner).order_by("id").values_list("id", flat=True).first()
        return obj.id == first_id

    def get_additional_portfolio_price(self, obj):
        return "9.99"


class PMPropertySerializer(serializers.ModelSerializer):
    class Meta:
        model = PMProperty
        fields = "__all__"
        read_only_fields = ("id", "workspace", "created_by", "created_at", "updated_at")

    def validate_state(self, value):
        return str(value or "").strip().upper()[:2]


class PMProjectUpdateSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PMProjectUpdate
        fields = "__all__"
        read_only_fields = ("id", "project", "created_by", "created_at", "created_by_name")

    def get_created_by_name(self, obj):
        user = obj.created_by
        return (user.get_full_name() or user.email) if user else "SyncWorks"

    def validate_progress_percent(self, value):
        if value is not None and value > 100:
            raise serializers.ValidationError("Progress cannot exceed 100%.")
        return value


class PMProjectSerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(source="property.name", read_only=True)
    updates = PMProjectUpdateSerializer(many=True, read_only=True)
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = PMProject
        fields = "__all__"
        read_only_fields = ("id", "workspace", "created_by", "created_at", "updated_at", "completed_at", "archived_at", "property_name", "updates", "is_overdue")

    def get_is_overdue(self, obj):
        from django.utils import timezone
        return bool(obj.target_date and obj.target_date < timezone.localdate() and obj.status not in {PMProject.Status.COMPLETED, PMProject.Status.ARCHIVED})

    def validate_progress_percent(self, value):
        if value > 100:
            raise serializers.ValidationError("Progress cannot exceed 100%.")
        return value

    def validate_property(self, value):
        request = self.context.get("request")
        if value and request and value.workspace.owner_id != request.user.id:
            raise serializers.ValidationError("Property is not available in this portfolio.")
        return value


class PMTenantSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    latest_invitation = serializers.SerializerMethodField()

    class Meta:
        model = PMTenant
        fields = "__all__"
        read_only_fields = ("id", "workspace", "user", "status", "created_by", "created_at", "updated_at")

    def to_internal_value(self, data):
        normalized = data.copy() if hasattr(data, "copy") else dict(data)
        for field in ("move_in_date", "lease_start", "lease_end", "monthly_rent"):
            if normalized.get(field) == "":
                normalized[field] = None
        for field in ("first_name", "last_name", "email", "phone", "property_name", "unit_label", "notes"):
            if isinstance(normalized.get(field), str):
                normalized[field] = normalized[field].strip()
        if isinstance(normalized.get("email"), str):
            normalized["email"] = normalized["email"].lower()
        return super().to_internal_value(normalized)

    def validate(self, attrs):
        lease_start = attrs.get("lease_start") or getattr(self.instance, "lease_start", None)
        lease_end = attrs.get("lease_end") or getattr(self.instance, "lease_end", None)
        if lease_start and lease_end and lease_end < lease_start:
            raise serializers.ValidationError({"lease_end": "Lease end must be on or after lease start."})
        return attrs

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    def get_latest_invitation(self, obj):
        invite = obj.invitations.order_by("-created_at").first()
        if not invite:
            return None
        return {"id": invite.id, "status": invite.status, "mode": invite.mode, "expires_at": invite.expires_at, "sent_at": invite.sent_at, "sent_to_email": invite.sent_to_email}


class PMTenantInvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMTenantInvitation
        fields = ("id", "tenant", "mode", "status", "code", "expires_at", "sent_to_email", "sent_from_name", "reply_to_email", "sent_at", "accepted_at", "revoked_at", "created_at")
        read_only_fields = fields
