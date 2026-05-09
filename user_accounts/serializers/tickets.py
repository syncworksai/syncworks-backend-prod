from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers
from django.contrib.auth import get_user_model

from user_accounts.models import (
    ServiceRequest,
    Ticket,
    TicketMessage,
    TicketAttachment,
    TicketQuote,
    Business,
    ServiceCategory,
    BusinessMember,
    InvoiceLineItem,
)
from user_accounts.models.billing import Invoice

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
            attrs["target_business"] = chosen
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
            "priority",
            "needed_by_date",
            "preferred_time_window",
            "preferred_start_date",
            "preferred_end_date",
            "intake_payload",
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
            "priority",
            "needed_by_date",
            "preferred_time_window",
            "preferred_start_date",
            "preferred_end_date",
            "intake_payload",
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


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    catalog_item_name = serializers.SerializerMethodField()
    line_cost_total = serializers.SerializerMethodField()
    line_profit_total = serializers.SerializerMethodField()
    line_margin_pct = serializers.SerializerMethodField()

    class Meta:
        model = InvoiceLineItem
        fields = [
            "id",
            "invoice",
            "catalog_item_id",
            "catalog_item_name",
            "name",
            "description",
            "item_type",
            "unit_label",
            "quantity",
            "unit_price",
            "unit_cost",
            "line_subtotal",
            "line_cost_total",
            "line_profit_total",
            "line_margin_pct",
            "sort_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_catalog_item_name(self, obj) -> str:
        try:
            if obj.catalog_item_id and obj.catalog_item:
                return obj.catalog_item.name or ""
        except Exception:
            pass
        return ""

    def get_line_cost_total(self, obj) -> str:
        try:
            return str(obj.line_cost_total)
        except Exception:
            return "0.00"

    def get_line_profit_total(self, obj) -> str:
        try:
            return str(obj.line_profit_total)
        except Exception:
            return "0.00"

    def get_line_margin_pct(self, obj) -> str:
        try:
            return str(obj.line_margin_pct)
        except Exception:
            return "0.00"


class InvoiceSerializer(serializers.ModelSerializer):
    line_items = InvoiceLineItemSerializer(many=True, read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "ticket",
            "title",
            "notes",
            "subtotal",
            "tax",
            "total",
            "status",
            "due_date",
            "payment_method",
            "amount_paid",
            "paid_at",
            "platform_fee_rate_bps",
            "platform_fee_amount",
            "platform_fee_collected",
            "platform_fee_collected_at",
            "stripe_checkout_session_id",
            "stripe_payment_intent_id",
            "stripe_charge_id",
            "stripe_transfer_id",
            "created_at",
            "updated_at",
            "line_items",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "platform_fee_amount",
            "platform_fee_collected",
            "platform_fee_collected_at",
            "paid_at",
            "line_items",
        ]


class AssignedBusinessCardSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()
    display_location = serializers.SerializerMethodField()

    class Meta:
        model = Business
        fields = [
            "id",
            "name",
            "logo_url",
            "headline",
            "services_text",
            "business_email",
            "phone",
            "address",
            "city",
            "state",
            "display_location",
            "website",
            "base_zip",
            "service_radius_miles",
            "accepts_marketplace_tickets",
            "business_card_code",
            "is_licensed",
            "is_insured",
            "is_bonded",
            "background_checked",
            "emergency_service",
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


class TicketSerializer(serializers.ModelSerializer):
    customer = serializers.PrimaryKeyRelatedField(read_only=True)

    ticket_code = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    service_address_display = serializers.SerializerMethodField()
    quick_summary = serializers.SerializerMethodField()

    category_name = serializers.SerializerMethodField()
    category_key = serializers.SerializerMethodField()
    category_path = serializers.SerializerMethodField()
    category_root_key = serializers.SerializerMethodField()

    latest_quote = serializers.SerializerMethodField()
    latest_invoice = serializers.SerializerMethodField()

    assigned_member_name = serializers.SerializerMethodField()
    assigned_business_name = serializers.SerializerMethodField()
    assigned_business_card = serializers.SerializerMethodField()

    is_archived = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "ticket_code",
            "customer",
            "customer_name",
            "service_address_display",
            "quick_summary",
            "service_request",
            "category",
            "category_name",
            "category_key",
            "category_path",
            "category_root_key",
            "status",
            "assigned_business",
            "assigned_business_name",
            "assigned_business_card",
            "assigned_member",
            "assigned_member_name",
            "is_marketplace",
            "service_address",
            "service_zip",
            "service_radius_miles",
            "payment_method",
            "total_amount_cents",
            "cash_confirmed_at",
            "cash_fee_invoiced_month",
            "archived_at",
            "is_archived",
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
            "ticket_code",
            "customer",
            "customer_name",
            "service_address_display",
            "quick_summary",
            "archived_at",
            "is_archived",
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
            "assigned_business_name",
            "assigned_business_card",
        ]

    def _is_customer_request(self) -> bool:
        try:
            request = self.context.get("request")
            user = getattr(request, "user", None)
            role = (getattr(user, "role", "") or "").upper()
            return role == "CUSTOMER"
        except Exception:
            return False

    def get_ticket_code(self, obj) -> str:
        try:
            return obj.ticket_code
        except Exception:
            try:
                prefix = "MP" if bool(getattr(obj, "is_marketplace", False)) else "DT"
                return f"{prefix}-{int(obj.id):06d}"
            except Exception:
                return "DT-000000"

    def get_customer_name(self, obj) -> str:
        try:
            return _user_display(getattr(obj, "customer", None))
        except Exception:
            return "Customer"

    def get_service_address_display(self, obj) -> str:
        try:
            if (obj.service_address or "").strip():
                return obj.service_address.strip()
        except Exception:
            pass
        try:
            sr = getattr(obj, "service_request", None)
            if sr and (sr.address or "").strip():
                return sr.address.strip()
        except Exception:
            pass
        return "No service address"

    def get_quick_summary(self, obj):
        try:
            return {
                "type": "Marketplace" if bool(obj.is_marketplace) else "Direct",
                "status": obj.status,
                "assigned": bool(obj.assigned_business_id),
                "payment": getattr(obj, "payment_method", "—"),
            }
        except Exception:
            return {}

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
        if self._is_customer_request():
            return None
        try:
            q = obj.quotes.order_by("-created_at").first()
            return TicketQuoteSerializer(q).data if q else None
        except Exception:
            return None

    def get_latest_invoice(self, obj):
        try:
            inv = obj.invoices.order_by("-created_at").prefetch_related("line_items").first()
            if not inv:
                return None

            if self._is_customer_request():
                visible_statuses = set()
                try:
                    visible_statuses.add(Invoice.Status.SENT)
                    visible_statuses.add(Invoice.Status.PAID)
                except Exception:
                    visible_statuses.update({"SENT", "PAID"})

                if str(getattr(inv, "status", "")).upper() not in {str(x).upper() for x in visible_statuses}:
                    return None

            return InvoiceSerializer(inv).data
        except Exception:
            return None

    def get_assigned_member_name(self, obj) -> str:
        try:
            return _user_display(getattr(obj, "assigned_member", None))
        except Exception:
            return ""

    def get_assigned_business_name(self, obj) -> str:
        try:
            if obj.assigned_business_id and obj.assigned_business:
                return obj.assigned_business.name or ""
        except Exception:
            pass
        return ""

    def get_assigned_business_card(self, obj):
        try:
            if obj.assigned_business_id and obj.assigned_business:
                return AssignedBusinessCardSerializer(
                    obj.assigned_business,
                    context=self.context,
                ).data
        except Exception:
            pass
        return None

    def get_is_archived(self, obj) -> bool:
        try:
            return bool(obj.archived_at)
        except Exception:
            return False


class TicketMessageSerializer(serializers.ModelSerializer):
    sender = serializers.PrimaryKeyRelatedField(read_only=True)

    author = serializers.SerializerMethodField()
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = TicketMessage
        fields = ["id", "ticket", "sender", "author", "author_name", "body", "type", "created_at"]
        read_only_fields = ["id", "sender", "author", "author_name", "type", "created_at"]

    def get_author(self, obj) -> str:
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