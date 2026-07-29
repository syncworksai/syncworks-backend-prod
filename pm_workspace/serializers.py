import calendar
from datetime import date, timedelta
from decimal import Decimal

from rest_framework import serializers

from .models import (
    PMDocumentPacket,
    PMLedgerEntry,
    PMLease,
    PMProject,
    PMProjectUpdate,
    PMProperty,
    PMProspect,
    PMTenant,
    PMTenantInvitation,
    PMUnit,
    PMWorkspace,
)


def add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


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
    available_units = serializers.SerializerMethodField()
    total_units = serializers.SerializerMethodField()

    class Meta:
        model = PMProperty
        fields = "__all__"
        read_only_fields = ("id", "workspace", "created_by", "created_at", "updated_at", "available_units", "total_units")

    def validate_state(self, value):
        return str(value or "").strip().upper()[:2]

    def get_available_units(self, obj):
        return obj.units.filter(availability=PMUnit.Availability.AVAILABLE).count()

    def get_total_units(self, obj):
        return obj.units.count()


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
    balance = serializers.SerializerMethodField()
    active_lease = serializers.SerializerMethodField()

    class Meta:
        model = PMTenant
        fields = "__all__"
        read_only_fields = ("id", "workspace", "user", "status", "created_by", "created_at", "updated_at", "balance", "active_lease")

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

    def get_balance(self, obj):
        total = Decimal("0.00")
        for entry in obj.ledger_entries.all():
            if entry.entry_type in {PMLedgerEntry.EntryType.CHARGE, PMLedgerEntry.EntryType.ADJUSTMENT}:
                total += entry.amount
            else:
                total -= entry.amount
        return str(total.quantize(Decimal("0.01")))

    def get_active_lease(self, obj):
        lease = obj.leases.exclude(status="ENDED").order_by("-start_date").first()
        return PMLeaseSerializer(lease).data if lease else None


class PMTenantInvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PMTenantInvitation
        fields = ("id", "tenant", "mode", "status", "code", "expires_at", "sent_to_email", "sent_from_name", "reply_to_email", "sent_at", "accepted_at", "revoked_at", "created_at")
        read_only_fields = fields


class PMUnitSerializer(serializers.ModelSerializer):
    property_name = serializers.CharField(source="property.name", read_only=True)
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = PMUnit
        fields = "__all__"
        read_only_fields = ("id", "workspace", "property_name", "display_name", "created_at", "updated_at")

    def get_display_name(self, obj):
        return f"{obj.property.name} · {obj.label}"

    def validate_property(self, value):
        request = self.context.get("request")
        if request and value.workspace.owner_id != request.user.id:
            raise serializers.ValidationError("Property is not available in this portfolio.")
        return value


class PMProspectSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    assigned_unit_name = serializers.CharField(source="assigned_unit.label", read_only=True)
    assigned_property_name = serializers.CharField(source="assigned_unit.property.name", read_only=True)

    class Meta:
        model = PMProspect
        fields = "__all__"
        read_only_fields = ("id", "workspace", "created_by", "created_at", "updated_at", "full_name", "assigned_unit_name", "assigned_property_name")

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    def to_internal_value(self, data):
        normalized = data.copy() if hasattr(data, "copy") else dict(data)
        for field in ("desired_move_in", "desired_bedrooms", "voucher_bedrooms", "max_rent", "assigned_unit", "showing_at"):
            if normalized.get(field) == "":
                normalized[field] = None
        return super().to_internal_value(normalized)


class PMLeaseSerializer(serializers.ModelSerializer):
    tenant_name = serializers.SerializerMethodField()
    unit_name = serializers.SerializerMethodField()

    class Meta:
        model = PMLease
        fields = "__all__"
        read_only_fields = ("id", "workspace", "tenant_name", "unit_name", "created_at", "updated_at")

    def get_tenant_name(self, obj):
        return f"{obj.tenant.first_name} {obj.tenant.last_name}".strip()

    def get_unit_name(self, obj):
        return f"{obj.unit.property.name} · {obj.unit.label}" if obj.unit else ""

    def validate(self, attrs):
        term = attrs.get("term", getattr(self.instance, "term", PMLease.Term.TWELVE_MONTH))
        start_date = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end_date = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start_date and term == PMLease.Term.SIX_MONTH:
            end_date = add_months(start_date, 6) - timedelta(days=1)
        elif start_date and term == PMLease.Term.TWELVE_MONTH:
            end_date = add_months(start_date, 12) - timedelta(days=1)
        elif term == PMLease.Term.MONTH_TO_MONTH:
            end_date = None
        if term == PMLease.Term.CUSTOM and not end_date:
            raise serializers.ValidationError({"end_date": "Custom leases require an end date."})
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError({"end_date": "Lease end must be on or after lease start."})
        attrs["end_date"] = end_date
        return attrs


class PMDocumentPacketSerializer(serializers.ModelSerializer):
    tenant_name = serializers.SerializerMethodField()
    prospect_name = serializers.SerializerMethodField()

    class Meta:
        model = PMDocumentPacket
        fields = "__all__"
        read_only_fields = ("id", "workspace", "created_at", "updated_at", "tenant_name", "prospect_name")

    def get_tenant_name(self, obj):
        return f"{obj.tenant.first_name} {obj.tenant.last_name}".strip() if obj.tenant else ""

    def get_prospect_name(self, obj):
        return f"{obj.prospect.first_name} {obj.prospect.last_name}".strip() if obj.prospect else ""

    def validate(self, attrs):
        if not attrs.get("tenant") and not attrs.get("prospect") and not getattr(self.instance, "tenant_id", None) and not getattr(self.instance, "prospect_id", None):
            raise serializers.ValidationError("Choose a tenant or prospect for this packet.")
        return attrs


class PMLedgerEntrySerializer(serializers.ModelSerializer):
    tenant_name = serializers.SerializerMethodField()

    class Meta:
        model = PMLedgerEntry
        fields = "__all__"
        read_only_fields = ("id", "workspace", "created_by", "created_at", "updated_at", "tenant_name")

    def get_tenant_name(self, obj):
        return f"{obj.tenant.first_name} {obj.tenant.last_name}".strip()

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value
