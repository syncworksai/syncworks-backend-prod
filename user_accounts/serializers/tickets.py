# user_accounts/serializers/tickets.py
from __future__ import annotations

from rest_framework import serializers
from django.db import models  # ✅ needed for fields - models references

from django.contrib.auth import get_user_model

from user_accounts.models import (
    ServiceRequest,
    Ticket,
    TicketMessage,
    TicketAttachment,
    TicketQuote,
    Invoice,
    Business,
    ServiceCategory,
    BusinessMember,
)

MIN_TICKET_RADIUS_MILES = 1
MAX_TICKET_RADIUS_MILES = 200

User = get_user_model()


def _norm_zip(z: str) -> str:
    z = (z or "").strip()
    if not z:
        return ""
    digits = "".join([c for c in z if c.isdigit()])
    if not digits:
        return ""
    return digits[:5]


def _category_path(cat: ServiceCategory | None) -> str:
    if not cat:
        return ""
    chain = []
    cur = cat
    guard = 0
    while cur is not None and guard < 20:
        chain.append(cur.name)
        cur = cur.parent
        guard += 1
    chain.reverse()
    return " → ".join(chain)


def _category_root(cat: ServiceCategory | None) -> ServiceCategory | None:
    if not cat:
        return None
    cur = cat
    guard = 0
    while cur.parent is not None and guard < 50:
        cur = cur.parent
        guard += 1
    return cur


def _user_display(u: User | None) -> str:
    if not u:
        return ""
    try:
        full = (getattr(u, "get_full_name", None)() or "").strip()
        if full:
            return full
    except Exception:
        pass
    for attr in ("name", "display_name", "username", "email"):
        try:
            v = (getattr(u, attr, "") or "").strip()
            if v:
                return v
        except Exception:
            continue
    return f"User #{getattr(u, 'id', '')}"


class ServiceRequestCreateSerializer(serializers.Serializer):
    category = serializers.IntegerField()
    title = serializers.CharField(max_length=160)
    description = serializers.CharField(required=False, allow_blank=True)
    preferred_sbo_user = serializers.IntegerField(required=False, allow_null=True)

    service_address = serializers.CharField(required=False, allow_blank=True, max_length=255)
    service_zip = serializers.CharField(required=False, allow_blank=True, max_length=20)
    service_radius_miles = serializers.IntegerField(required=False, allow_null=True)
    is_marketplace = serializers.BooleanField(required=False, default=False)

    # ✅ NEW: Direct business routing (accept either key for compatibility)
    # Frontend can send business_id (from favorites) or target_business
    business_id = serializers.IntegerField(required=False, allow_null=True)
    target_business = serializers.IntegerField(required=False, allow_null=True)

    def validate_service_radius_miles(self, v):
        if v is None:
            return None
        try:
            v = int(v)
        except Exception:
            raise serializers.ValidationError("service_radius_miles must be an integer.")
        if v < MIN_TICKET_RADIUS_MILES or v > MAX_TICKET_RADIUS_MILES:
            raise serializers.ValidationError(
                f"service_radius_miles must be between {MIN_TICKET_RADIUS_MILES} and {MAX_TICKET_RADIUS_MILES}."
            )
        return v

    def validate(self, attrs):
        # ✅ normalize business target
        tb = attrs.get("target_business", None)
        bid = attrs.get("business_id", None)
        chosen = tb if tb is not None else bid
        if chosen is not None:
            try:
                chosen = int(chosen)
            except Exception:
                raise serializers.ValidationError({"business_id": "business_id must be an integer."})
            if chosen <= 0:
                raise serializers.ValidationError({"business_id": "business_id must be > 0."})
            attrs["target_business"] = chosen  # store normalized key
            # Direct request forces marketplace off
            attrs["is_marketplace"] = False

        is_marketplace = bool(attrs.get("is_marketplace", False))
        if is_marketplace:
            z = _norm_zip(attrs.get("service_zip", "") or "")
            if not z:
                raise serializers.ValidationError({"service_zip": "ZIP is required for marketplace tickets."})
        return attrs


class ServiceRequestSerializer(serializers.ModelSerializer):
    ticket_id = serializers.SerializerMethodField()
    ticket_status = serializers.SerializerMethodField()

    category_name = serializers.SerializerMethodField()
    category_key = serializers.SerializerMethodField()
    category_path = serializers.SerializerMethodField()
    category_root_key = serializers.SerializerMethodField()

    service_address = serializers.SerializerMethodField()
    service_zip = serializers.SerializerMethodField()
    service_radius_miles = serializers.SerializerMethodField()
    is_marketplace = serializers.SerializerMethodField()

    # ✅ NEW: Direct routing output helpers
    target_business_id = serializers.SerializerMethodField()
    target_business_name = serializers.SerializerMethodField()

    class Meta:
        model = ServiceRequest
        fields = [
            "id",
            "customer",
            "category",
            "category_name",
            "category_key",
            "category_path",
            "category_root_key",
            "title",
            "description",
            "preferred_sbo_user",
            "target_business_id",
            "target_business_name",
            "created_at",
            "service_address",
            "service_zip",
            "service_radius_miles",
            "is_marketplace",
            "ticket_id",
            "ticket_status",
            "address",
            "zip_code",
        ]
        read_only_fields = [
            "id",
            "customer",
            "created_at",
            "ticket_id",
            "ticket_status",
            "category_name",
            "category_key",
            "category_path",
            "category_root_key",
            "service_address",
            "service_zip",
            "service_radius_miles",
            "is_marketplace",
            "target_business_id",
            "target_business_name",
        ]

    def _ticket(self, obj) -> Ticket | None:
        try:
            return obj.ticket
        except Exception:
            return None

    def get_ticket_id(self, obj) -> int | None:
        t = self._ticket(obj)
        return t.id if t else None

    def get_ticket_status(self, obj) -> str:
        t = self._ticket(obj)
        try:
            return t.status if t else ""
        except Exception:
            return ""

    def get_category_name(self, obj) -> str:
        try:
            return obj.category.name if obj.category_id else ""
        except Exception:
            return ""

    def get_category_key(self, obj) -> str:
        try:
            return obj.category.key if obj.category_id else ""
        except Exception:
            return ""

    def get_category_path(self, obj) -> str:
        try:
            return _category_path(obj.category) if obj.category_id else ""
        except Exception:
            return ""

    def get_category_root_key(self, obj) -> str:
        try:
            root = _category_root(obj.category) if obj.category_id else None
            return root.key if root else ""
        except Exception:
            return ""

    def get_service_address(self, obj) -> str:
        t = self._ticket(obj)
        if t:
            try:
                return (t.service_address or "").strip()
            except Exception:
                pass
        try:
            return (obj.address or "").strip()
        except Exception:
            return ""

    def get_service_zip(self, obj) -> str:
        t = self._ticket(obj)
        if t:
            try:
                return (t.service_zip or "").strip()
            except Exception:
                pass
        try:
            return (obj.zip_code or "").strip()
        except Exception:
            return ""

    def get_service_radius_miles(self, obj) -> int | None:
        t = self._ticket(obj)
        if t:
            try:
                return t.service_radius_miles
            except Exception:
                pass
        return None

    def get_is_marketplace(self, obj) -> bool:
        t = self._ticket(obj)
        if t:
            try:
                return bool(t.is_marketplace)
            except Exception:
                pass
        return False

    def get_target_business_id(self, obj) -> int | None:
        try:
            return obj.target_business_id
        except Exception:
            return None

    def get_target_business_name(self, obj) -> str:
        try:
            if obj.target_business_id and obj.target_business:
                return obj.target_business.name or ""
        except Exception:
            pass
        return ""


class BusinessMemberLiteSerializer(serializers.ModelSerializer):
    """
    Lightweight assignee list for UI pickers.
    """
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    name = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()

    class Meta:
        model = BusinessMember
        fields = [
            "id",
            "user_id",
            "name",
            "role",
            "is_active",
            "is_owner",
            "can_assign_tickets",
            "can_close_tickets",
        ]
        read_only_fields = fields

    def get_name(self, obj) -> str:
        try:
            return _user_display(getattr(obj, "user", None))
        except Exception:
            return ""

    def get_role(self, obj) -> str:
        try:
            return (getattr(obj, "role", "") or "").upper()
        except Exception:
            return ""


class TicketQuoteSerializer(serializers.ModelSerializer):
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)
    approved_by = serializers.PrimaryKeyRelatedField(read_only=True)
    rejected_by = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = TicketQuote
        fields = [
            "id",
            "ticket",
            "created_by",
            "amount",
            "details",
            "status",
            "sent_at",
            "approved_by",
            "approved_at",
            "rejected_by",
            "rejected_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "status",
            "sent_at",
            "approved_by",
            "approved_at",
            "rejected_by",
            "rejected_at",
            "created_at",
        ]


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = "__all__"
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "platform_fee_amount",
            "platform_fee_collected",
            "platform_fee_collected_at",
            "paid_at",
        ]


class TicketSerializer(serializers.ModelSerializer):
    customer = serializers.PrimaryKeyRelatedField(read_only=True)

    category_name = serializers.SerializerMethodField()
    category_key = serializers.SerializerMethodField()
    category_path = serializers.SerializerMethodField()
    category_root_key = serializers.SerializerMethodField()

    latest_quote = serializers.SerializerMethodField()
    latest_invoice = serializers.SerializerMethodField()

    # ✅ UI helpers
    assigned_member_name = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "service_request",
            "customer",
            "category",
            "category_name",
            "category_key",
            "category_path",
            "category_root_key",
            "status",
            "assigned_business",
            "assigned_member",
            "assigned_member_name",
            "is_marketplace",
            "service_address",
            "service_zip",
            "service_radius_miles",
            "created_at",
            "assigned_at",
            "accepted_at",
            "scheduled_at",
            "en_route_at",
            "on_site_at",
            "started_at",
            "awaiting_approval_at",
            "completed_at",
            "invoiced_at",
            "paid_at",
            "closed_at",
            "cancelled_at",
            "latest_quote",
            "latest_invoice",
        ]
        read_only_fields = [
            "id",
            "customer",
            "created_at",
            "assigned_at",
            "accepted_at",
            "scheduled_at",
            "en_route_at",
            "on_site_at",
            "started_at",
            "awaiting_approval_at",
            "completed_at",
            "invoiced_at",
            "paid_at",
            "closed_at",
            "cancelled_at",
            "category_name",
            "category_key",
            "category_path",
            "category_root_key",
            "latest_quote",
            "latest_invoice",
            "assigned_member_name",
        ]

    def get_category_name(self, obj) -> str:
        try:
            return obj.category.name if obj.category_id else ""
        except Exception:
            return ""

    def get_category_key(self, obj) -> str:
        try:
            return obj.category.key if obj.category_id else ""
        except Exception:
            return ""

    def get_category_path(self, obj) -> str:
        try:
            return _category_path(obj.category) if obj.category_id else ""
        except Exception:
            return ""

    def get_category_root_key(self, obj) -> str:
        try:
            root = _category_root(obj.category) if obj.category_id else None
            return root.key if root else ""
        except Exception:
            return ""

    def get_latest_quote(self, obj):
        try:
            q = obj.quotes.order_by("-created_at").first()
            return TicketQuoteSerializer(q).data if q else None
        except Exception:
            return None

    def get_latest_invoice(self, obj):
        try:
            inv = obj.invoices.order_by("-created_at").first()
            return InvoiceSerializer(inv).data if inv else None
        except Exception:
            return None

    def get_assigned_member_name(self, obj) -> str:
        try:
            return _user_display(getattr(obj, "assigned_member", None))
        except Exception:
            return ""


class TicketMessageSerializer(serializers.ModelSerializer):
    sender = serializers.PrimaryKeyRelatedField(read_only=True)

    # ✅ Frontend compatibility (MessagePanel.jsx uses author_name || author || "SYSTEM")
    author = serializers.SerializerMethodField()
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = TicketMessage
        fields = ["id", "ticket", "sender", "author", "author_name", "body", "type", "created_at"]
        read_only_fields = ["id", "sender", "author", "author_name", "type", "created_at"]

    def get_author(self, obj) -> str:
        # Keep lightweight string fallback
        try:
            if obj.sender_id:
                return str(obj.sender_id)
        except Exception:
            pass
        return "SYSTEM"

    def get_author_name(self, obj) -> str:
        try:
            if obj.sender_id:
                return _user_display(obj.sender)
        except Exception:
            pass
        return "SYSTEM"


class TicketAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.PrimaryKeyRelatedField(read_only=True)

    # ✅ AttachmentPanel.jsx expects file_url + filename + size_bytes
    file_url = serializers.SerializerMethodField()
    size_bytes = serializers.SerializerMethodField()
    filename = serializers.SerializerMethodField()

    class Meta:
        model = TicketAttachment
        fields = ["id", "ticket", "uploaded_by", "file", "file_url", "filename", "size_bytes", "created_at"]
        read_only_fields = ["id", "uploaded_by", "file_url", "filename", "size_bytes", "created_at"]

    def get_file_url(self, obj) -> str:
        try:
            if obj.file and hasattr(obj.file, "url"):
                return obj.file.url
        except Exception:
            pass
        return ""

    def get_size_bytes(self, obj) -> int:
        try:
            if obj.file and hasattr(obj.file, "size"):
                return int(obj.file.size or 0)
        except Exception:
            pass
        return 0

    def get_filename(self, obj) -> str:
        try:
            if getattr(obj, "filename", ""):
                return obj.filename
        except Exception:
            pass
        try:
            if obj.file:
                return (obj.file.name or "").split("/")[-1]
        except Exception:
            pass
        return ""


class EligibleBusinessSerializer(serializers.ModelSerializer):
    """
    Returned in marketplace eligibility lists.
    Keep minimal + UI-ready.
    """
    name = serializers.CharField(read_only=True)

    class Meta:
        model = Business
        fields = [
            "id",
            "name",
            "base_zip",
            "service_radius_miles",
            "accepts_marketplace_tickets",
        ]
        read_only_fields = fields
