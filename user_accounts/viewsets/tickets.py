from __future__ import annotations

from typing import Optional, Any, Dict
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q, Case, When, IntegerField, Value
from django.template import Context, Engine, TemplateSyntaxError

from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import (
    Ticket,
    Business,
    BusinessMember,
    TicketMessage,
    TicketAttachment,
    TicketQuote,
    TicketViewEvent,
    DocumentTemplate,
    PlatformBillingProfile,
)
from user_accounts.models.billing import Invoice

try:
    from user_accounts.models.business_access import BusinessAccessControl
except Exception:
    BusinessAccessControl = None  # type: ignore

from user_accounts.serializers.tickets import (
    TicketSerializer,
    TicketMessageSerializer,
    TicketAttachmentSerializer,
    TicketQuoteSerializer,
    InvoiceSerializer,
    EligibleBusinessSerializer,
)

from user_accounts.services.permissions import get_active_membership
from user_accounts.permissions import TicketParticipantRequired

from user_accounts.services.tickets import (
    ticket_eligible_businesses,
    assign_ticket_to_business,
    send_ticket_to_marketplace,
    marketplace_tickets_for_business,
    is_ticket_eligible_for_business,
    provider_accept,
    provider_start,
    provider_complete,
    cancel_ticket,
    provider_set_needs_quote,
    provider_send_quote,
    customer_approve_quote,
    customer_reject_quote,
    provider_send_invoice,
)


def role_is(u, *names: str) -> bool:
    r = (getattr(u, "role", "") or "").upper()
    return r in {n.upper() for n in names}


def _employee_can_change_status(mem: Optional[BusinessMember]) -> bool:
    if not mem:
        return False
    return bool(getattr(mem, "can_assign_tickets", False) or getattr(mem, "can_close_tickets", False))


def _employee_can_assign(mem: Optional[BusinessMember]) -> bool:
    if not mem:
        return False
    return bool(getattr(mem, "can_assign_tickets", False))


def _get_active_business_from_request(request) -> Business | None:
    raw = (
        request.headers.get("X-Business-Id")
        or request.headers.get("x-business-id")
        or request.query_params.get("business_id")
        or ""
    )
    raw = str(raw).strip()
    if not raw:
        return None

    try:
        biz_id = int(raw)
    except Exception:
        return None

    biz = Business.objects.filter(id=biz_id, is_active=True).first()
    if not biz:
        return None

    u = request.user
    if getattr(u, "is_superuser", False) or getattr(u, "is_platform_admin", False):
        return biz

    if getattr(biz, "owner_id", None) == getattr(u, "id", None):
        return biz

    mem = BusinessMember.objects.filter(user_id=u.id, business_id=biz.id, is_active=True).first()
    if mem:
        return biz

    return None


def _system_msg(ticket: Ticket, sender_user, body: str):
    TicketMessage.objects.create(
        ticket=ticket,
        sender=sender_user,
        body=body,
        type=TicketMessage.MessageType.SYSTEM,
    )


def _d(v: Any, default: str = "0.00") -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal(default)


def _money_to_cents(v: Any) -> int:
    amt = _d(v, "0.00")
    return int((amt * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _render_template_body(body: str, ctx: Dict[str, Any]) -> str:
    engine = Engine(debug=False, autoescape=False)
    compiled = engine.from_string(body or "")
    return compiled.render(Context(ctx or {}))


def _invoice_field_names() -> set[str]:
    out: set[str] = set()
    try:
        for f in Invoice._meta.get_fields():
            name = getattr(f, "name", None)
            if name:
                out.add(str(name))
    except Exception:
        pass
    return out


def _invoice_has(field_name: str) -> bool:
    return field_name in _invoice_field_names()


def _build_invoice_create_kwargs(
    *,
    ticket: Ticket,
    active_biz: Business,
    actor_user,
    title: str,
    notes: str,
    subtotal: Decimal,
    tax: Decimal,
    total: Decimal,
    due_date,
    payment_method: str,
) -> dict[str, Any]:
    fields = _invoice_field_names()
    kwargs: dict[str, Any] = {}

    # Linkage fields
    if "ticket" in fields:
        kwargs["ticket"] = ticket
    elif "ticket_id" in fields:
        kwargs["ticket_id"] = ticket.id

    if "service_request" in fields and getattr(ticket, "service_request_id", None):
        kwargs["service_request_id"] = ticket.service_request_id
    elif "service_request_id" in fields and getattr(ticket, "service_request_id", None):
        kwargs["service_request_id"] = ticket.service_request_id

    if "business" in fields:
        kwargs["business"] = active_biz
    elif "business_id" in fields:
        kwargs["business_id"] = active_biz.id

    if "created_by" in fields:
        kwargs["created_by"] = actor_user
    elif "created_by_id" in fields and getattr(actor_user, "id", None):
        kwargs["created_by_id"] = actor_user.id

    # Descriptive fields
    if "title" in fields:
        kwargs["title"] = title
    elif "name" in fields:
        kwargs["name"] = title

    if "notes" in fields:
        kwargs["notes"] = notes
    elif "memo" in fields:
        kwargs["memo"] = notes

    # Money fields
    if "subtotal" in fields:
        kwargs["subtotal"] = subtotal
    if "tax" in fields:
        kwargs["tax"] = tax
    if "total" in fields:
        kwargs["total"] = total
    if "amount" in fields:
        kwargs["amount"] = total
    if "amount_cents" in fields:
        kwargs["amount_cents"] = _money_to_cents(total)

    # Generic invoice fields from your current billing model
    if "kind" in fields:
        kwargs["kind"] = "JOB"
    if "status" in fields:
        kwargs["status"] = "OPEN"
    if "currency" in fields:
        kwargs["currency"] = "usd"
    if "due_date" in fields:
        kwargs["due_date"] = due_date
    if "payment_method" in fields:
        kwargs["payment_method"] = payment_method

    return kwargs


def _invoice_belongs_to_ticket(inv: Invoice, ticket: Ticket) -> bool:
    try:
        if getattr(inv, "ticket_id", None) is not None:
            return int(inv.ticket_id) == int(ticket.id)
    except Exception:
        pass

    try:
        if getattr(inv, "service_request_id", None) is not None and getattr(ticket, "service_request_id", None) is not None:
            return int(inv.service_request_id) == int(ticket.service_request_id)
    except Exception:
        pass

    try:
        if getattr(inv, "business_id", None) is not None and getattr(ticket, "assigned_business_id", None) is not None:
            return int(inv.business_id) == int(ticket.assigned_business_id)
    except Exception:
        pass

    return False


LOCKED_DETAIL = "Business account is locked. Update billing or submit an unlock request."


def _locked_payload(business_id: int, lock_reason: str = "") -> Dict[str, Any]:
    return {
        "detail": LOCKED_DETAIL,
        "lock_reason": lock_reason or "",
        "business_id": business_id,
    }


def _get_lock_state_for_business(biz: Business) -> tuple[bool, str]:
    try:
        p = PlatformBillingProfile.objects.filter(business_id=biz.id).only("is_locked", "lock_reason").first()
        if p and bool(getattr(p, "is_locked", False)):
            return True, str(getattr(p, "lock_reason", "") or "")
    except Exception:
        pass

    if BusinessAccessControl is not None:
        try:
            a = (
                BusinessAccessControl.objects.filter(business_id=biz.id)
                .only("is_locked", "lock_reason")
                .first()
            )
            if a and bool(getattr(a, "is_locked", False)):
                return True, str(getattr(a, "lock_reason", "") or "")
        except Exception:
            pass

    return False, ""


def _enforce_business_not_locked(biz: Business) -> Optional[Response]:
    locked, reason = _get_lock_state_for_business(biz)
    if not locked:
        return None
    return Response(_locked_payload(biz.id, reason), status=423)


class BusinessMemberLiteSerializer(serializers.ModelSerializer):
    user_email = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = BusinessMember
        fields = ["id", "role", "is_active", "user_id", "user_email", "user_name"]

    def get_user_email(self, obj) -> str:
        try:
            return obj.user.email or ""
        except Exception:
            return ""

    def get_user_name(self, obj) -> str:
        try:
            fn = (obj.user.first_name or "").strip()
            ln = (obj.user.last_name or "").strip()
            name = (fn + " " + ln).strip()
            return name or (obj.user.email or "")
        except Exception:
            return ""


class TicketViewSet(viewsets.ModelViewSet):
    serializer_class = TicketSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def get_queryset(self):
        u = self.request.user
        qs = (
            Ticket.objects.all()
            .select_related("category", "assigned_business", "assigned_member", "customer", "service_request")
            .order_by("-created_at")
        )

        if getattr(u, "is_superuser", False) or getattr(u, "is_platform_admin", False):
            return qs

        if role_is(u, "CUSTOMER"):
            return qs.filter(customer_id=u.id)

        active_biz = _get_active_business_from_request(self.request)
        if active_biz:
            return qs.filter(assigned_business_id=active_biz.id).distinct().order_by("-created_at")

        if role_is(u, "SBO"):
            business = Business.objects.filter(owner_id=u.id, is_active=True).order_by("id").first()
            if not business:
                return qs.none()
            return qs.filter(assigned_business_id=business.id).distinct().order_by("-created_at")

        if role_is(u, "EMPLOYEE"):
            biz_ids = list(
                BusinessMember.objects.filter(user_id=u.id, is_active=True).values_list("business_id", flat=True)
            )
            if not biz_ids:
                return qs.none()
            return qs.filter(assigned_business_id__in=biz_ids).distinct().order_by("-created_at")

        return qs.none()

    def perform_create(self, serializer):
        serializer.save(customer=self.request.user)

    @action(detail=False, methods=["get"], url_path="my")
    def my(self, request):
        return Response(TicketSerializer(self.get_queryset(), many=True, context=self.get_serializer_context()).data)

    @action(detail=False, methods=["get"], url_path="marketplace")
    def marketplace(self, request):
        u = request.user
        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers do not have a marketplace queue."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if not active_biz:
            return Response({"detail": "X-Business-Id required."}, status=400)

        locked_resp = _enforce_business_not_locked(active_biz)
        if locked_resp:
            return locked_resp

        qs = marketplace_tickets_for_business(active_biz)
        return Response(TicketSerializer(qs, many=True, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["get"], url_path="eligible-providers")
    def eligible_providers(self, request, pk=None):
        ticket = self.get_object()
        if not (
            role_is(request.user, "CUSTOMER")
            or getattr(request.user, "is_superuser", False)
            or getattr(request.user, "is_platform_admin", False)
        ):
            return Response({"detail": "Only customer can view eligible providers."}, status=403)

        businesses = ticket_eligible_businesses(ticket)
        return Response(EligibleBusinessSerializer(businesses, many=True).data)

    @action(detail=True, methods=["post"], url_path="assign-sbo")
    def assign_sbo(self, request, pk=None):
        ticket = self.get_object()
        if not (
            role_is(request.user, "CUSTOMER")
            or getattr(request.user, "is_superuser", False)
            or getattr(request.user, "is_platform_admin", False)
        ):
            return Response({"detail": "Only customer can assign provider."}, status=403)

        business_id = request.data.get("business_id")
        if not business_id:
            return Response({"detail": "business_id required"}, status=400)

        business = Business.objects.get(id=business_id, is_active=True)
        assign_ticket_to_business(ticket, business, assigned_member=None)
        ticket.refresh_from_db()
        return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="send-to-marketplace")
    def send_to_marketplace(self, request, pk=None):
        ticket = self.get_object()
        if not (
            role_is(request.user, "CUSTOMER")
            or getattr(request.user, "is_superuser", False)
            or getattr(request.user, "is_platform_admin", False)
        ):
            return Response({"detail": "Only customer can send to marketplace."}, status=403)

        try:
            send_ticket_to_marketplace(ticket)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        ticket.refresh_from_db()
        return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

    @action(detail=False, methods=["get"], url_path="assignees")
    def assignees(self, request):
        u = request.user
        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers do not have assignees."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if not active_biz:
            return Response({"detail": "X-Business-Id required."}, status=400)

        locked_resp = _enforce_business_not_locked(active_biz)
        if locked_resp:
            return locked_resp

        role = (request.query_params.get("role") or "").strip().upper()
        q = (request.query_params.get("q") or "").strip()

        qs = BusinessMember.objects.select_related("user").filter(business_id=active_biz.id, is_active=True)
        if role:
            qs = qs.filter(role=role)

        if q:
            qs = qs.filter(
                Q(user__email__icontains=q)
                | Q(user__username__icontains=q)
                | Q(user__first_name__icontains=q)
                | Q(user__last_name__icontains=q)
            )

        role_priority = ["OWNER", "MANAGER", "DISPATCH", "TECHNICIAN", "TECH", "ACCOUNTING", "ADMIN"]
        whens = [When(role=r, then=Value(i)) for i, r in enumerate(role_priority)]
        qs = qs.annotate(_role_rank=Case(*whens, default=Value(999), output_field=IntegerField())).order_by(
            "_role_rank", "id"
        )[:200]

        return Response(BusinessMemberLiteSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"], url_path="assign_member")
    def assign_member(self, request, pk=None):
        u = request.user
        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot assign members."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if not active_biz:
            return Response({"detail": "X-Business-Id required."}, status=400)

        locked_resp = _enforce_business_not_locked(active_biz)
        if locked_resp:
            return locked_resp

        ticket = self.get_object()

        if not ticket.assigned_business_id:
            assign_ticket_to_business(ticket, active_biz)
        elif ticket.assigned_business_id != active_biz.id:
            return Response({"detail": "Ticket is assigned to a different business."}, status=403)

        mem = get_active_membership(u, active_biz.id)
        if mem and not _employee_can_assign(mem) and getattr(active_biz, "owner_id", None) != u.id:
            return Response({"detail": "Not allowed."}, status=403)

        member_id = request.data.get("business_member_id")
        if not member_id:
            return Response({"detail": "business_member_id required"}, status=400)

        try:
            bm = BusinessMember.objects.select_related("user").get(
                id=int(member_id), business_id=active_biz.id, is_active=True
            )
        except Exception:
            return Response({"detail": "BusinessMember not found"}, status=404)

        ticket.assigned_member_id = bm.user_id
        ticket.save(update_fields=["assigned_member_id"])

        _system_msg(ticket, u, f"Assigned to {bm.user.email if bm.user_id else 'member'}.")
        ticket.refresh_from_db()
        return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="unassign_member")
    def unassign_member(self, request, pk=None):
        u = request.user
        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot unassign members."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if not active_biz:
            return Response({"detail": "X-Business-Id required."}, status=400)

        locked_resp = _enforce_business_not_locked(active_biz)
        if locked_resp:
            return locked_resp

        ticket = self.get_object()
        if ticket.assigned_business_id and ticket.assigned_business_id != active_biz.id:
            return Response({"detail": "Ticket is assigned to a different business."}, status=403)

        mem = get_active_membership(u, active_biz.id)
        if mem and not _employee_can_assign(mem) and getattr(active_biz, "owner_id", None) != u.id:
            return Response({"detail": "Not allowed."}, status=403)

        ticket.assigned_member = None
        ticket.save(update_fields=["assigned_member"])

        _system_msg(ticket, u, "Unassigned technician/member.")
        ticket.refresh_from_db()
        return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="create_invoice")
    def create_invoice(self, request, pk=None):
        u = request.user
        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot create invoices."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if not active_biz:
            return Response({"detail": "X-Business-Id required."}, status=400)

        locked_resp = _enforce_business_not_locked(active_biz)
        if locked_resp:
            return locked_resp

        ticket = self.get_object()

        if not ticket.assigned_business_id:
            assign_ticket_to_business(ticket, active_biz)
        elif ticket.assigned_business_id != active_biz.id:
            return Response({"detail": "Ticket is assigned to a different business."}, status=403)

        mem = get_active_membership(u, active_biz.id)
        if mem and not getattr(mem, "can_manage_invoices", False) and getattr(active_biz, "owner_id", None) != u.id:
            return Response({"detail": "Not allowed."}, status=403)

        payload = request.data or {}

        template_id = payload.get("template_id")
        context = payload.get("context") or {}

        title = (payload.get("title") or "").strip()
        notes = (payload.get("notes") or "").strip()

        subtotal = _d(payload.get("subtotal", payload.get("amount", "0.00")))
        tax = _d(payload.get("tax", "0.00"))
        total = _d(payload.get("total", subtotal + tax))

        due_date = payload.get("due_date") or None

        allowed_payment_methods = {"CARD", "CASH", "OTHER"}
        payment_method = str(payload.get("payment_method") or "CARD").strip().upper()
        if payment_method not in allowed_payment_methods:
            return Response({"detail": "Invalid payment_method."}, status=400)

        if template_id:
            tpl = DocumentTemplate.objects.filter(id=template_id, business_id=active_biz.id, is_active=True).first()
            if not tpl:
                return Response({"detail": "Template not found for this business."}, status=404)

            ctx: Dict[str, Any] = {}
            if isinstance(context, dict):
                ctx.update(context)

            ctx.setdefault("ticket_id", ticket.id)
            ctx.setdefault("subtotal", str(subtotal))
            ctx.setdefault("tax", str(tax))
            ctx.setdefault("total", str(total))
            ctx.setdefault("amount", str(total))

            try:
                rendered = _render_template_body(tpl.body or "", ctx)
            except TemplateSyntaxError as e:
                return Response({"detail": "Template syntax error", "error": str(e)}, status=400)
            except Exception as e:
                return Response({"detail": "Render failed", "error": str(e)}, status=400)

            if not title:
                title = tpl.name or "Invoice"
            notes = rendered

        if not title:
            title = "Invoice"

        create_kwargs = _build_invoice_create_kwargs(
            ticket=ticket,
            active_biz=active_biz,
            actor_user=u,
            title=title,
            notes=notes,
            subtotal=subtotal,
            tax=tax,
            total=total,
            due_date=due_date,
            payment_method=payment_method,
        )

        inv = Invoice.objects.create(**create_kwargs)

        _system_msg(ticket, u, f"Invoice created (#{inv.id}).")
        return Response(InvoiceSerializer(inv).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="mark_viewed")
    def mark_viewed(self, request, pk=None):
        ticket = self.get_object()
        u = request.user

        if role_is(u, "CUSTOMER"):
            return Response({"ok": True, "skipped": True})

        active_biz = _get_active_business_from_request(request)
        if not active_biz:
            return Response({"detail": "X-Business-Id required."}, status=400)

        locked_resp = _enforce_business_not_locked(active_biz)
        if locked_resp:
            return locked_resp

        if ticket.is_marketplace and not is_ticket_eligible_for_business(ticket, active_biz):
            return Response({"detail": "Ticket not eligible for your business region/services."}, status=403)

        TicketViewEvent.objects.create(
            ticket=ticket,
            actor=u,
            business=active_biz,
            event_type=TicketViewEvent.EventType.BUSINESS_VIEWED,
        )

        _system_msg(ticket, u, f"{active_biz.name} viewed marketplace ticket.")
        return Response({"ok": True, "ticket_id": ticket.id})

    @action(detail=True, methods=["post"], url_path="decline_marketplace")
    def decline_marketplace(self, request, pk=None):
        ticket = self.get_object()
        u = request.user

        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot decline marketplace tickets."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if not active_biz:
            return Response({"detail": "X-Business-Id required."}, status=400)

        if not ticket.is_marketplace:
            return Response({"detail": "Ticket is not a marketplace ticket."}, status=400)

        if ticket.assigned_business_id is not None:
            return Response({"detail": "Ticket is already assigned."}, status=400)

        if not is_ticket_eligible_for_business(ticket, active_biz):
            return Response({"detail": "Ticket not eligible for your business region/services."}, status=403)

        TicketViewEvent.objects.create(
            ticket=ticket,
            actor=u,
            business=active_biz,
            event_type=TicketViewEvent.EventType.DECLINED_MARKETPLACE,
        )

        _system_msg(ticket, u, f"{active_biz.name} declined marketplace ticket.")
        return Response({"ok": True, "ticket_id": ticket.id, "business_id": active_biz.id})

    @action(detail=True, methods=["post"], url_path="accept")
    def accept(self, request, pk=None):
        ticket = self.get_object()
        u = request.user

        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot accept tickets."}, status=403)

        active_biz = _get_active_business_from_request(request)

        if active_biz:
            locked_resp = _enforce_business_not_locked(active_biz)
            if locked_resp:
                return locked_resp

            if ticket.is_marketplace and not is_ticket_eligible_for_business(ticket, active_biz):
                return Response({"detail": "Ticket not eligible for your business region/services."}, status=403)

            if not ticket.assigned_business_id:
                assign_ticket_to_business(ticket, active_biz)

            mem = get_active_membership(u, active_biz.id)
            if mem and not _employee_can_change_status(mem) and getattr(active_biz, "owner_id", None) != u.id:
                return Response({"detail": "Not allowed."}, status=403)

            provider_accept(ticket, u)
            ticket.refresh_from_db()
            return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

        if role_is(u, "SBO"):
            business = Business.objects.filter(owner_id=u.id, is_active=True).order_by("id").first()
            if not business:
                return Response({"detail": "No active business found for SBO."}, status=400)

            locked_resp = _enforce_business_not_locked(business)
            if locked_resp:
                return locked_resp

            if ticket.is_marketplace and not is_ticket_eligible_for_business(ticket, business):
                return Response({"detail": "Ticket not eligible for your business region/services."}, status=403)

            if not ticket.assigned_business_id:
                assign_ticket_to_business(ticket, business)

            provider_accept(ticket, u)
            ticket.refresh_from_db()
            return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

        if role_is(u, "EMPLOYEE"):
            if not ticket.assigned_business_id:
                return Response({"detail": "Ticket not assigned to a business."}, status=400)

            biz = Business.objects.filter(id=ticket.assigned_business_id, is_active=True).first()
            if biz:
                locked_resp = _enforce_business_not_locked(biz)
                if locked_resp:
                    return locked_resp

            mem = get_active_membership(u, ticket.assigned_business_id)
            if not _employee_can_change_status(mem):
                return Response({"detail": "Not allowed."}, status=403)

            provider_accept(ticket, u)
            ticket.refresh_from_db()
            return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

        return Response({"detail": "Only provider can accept."}, status=403)

    @action(detail=True, methods=["post"], url_path="start")
    def start(self, request, pk=None):
        ticket = self.get_object()
        u = request.user

        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot start tickets."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if active_biz:
            locked_resp = _enforce_business_not_locked(active_biz)
            if locked_resp:
                return locked_resp

            mem = get_active_membership(u, active_biz.id)
            if mem and not _employee_can_change_status(mem) and getattr(active_biz, "owner_id", None) != u.id:
                return Response({"detail": "Not allowed."}, status=403)
            provider_start(ticket, u)
            ticket.refresh_from_db()
            return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

        if role_is(u, "SBO"):
            business = Business.objects.filter(owner_id=u.id, is_active=True).order_by("id").first()
            if business:
                locked_resp = _enforce_business_not_locked(business)
                if locked_resp:
                    return locked_resp
            provider_start(ticket, u)
            ticket.refresh_from_db()
            return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

        if role_is(u, "EMPLOYEE"):
            if not ticket.assigned_business_id:
                return Response({"detail": "Ticket not assigned to a business."}, status=400)

            biz = Business.objects.filter(id=ticket.assigned_business_id, is_active=True).first()
            if biz:
                locked_resp = _enforce_business_not_locked(biz)
                if locked_resp:
                    return locked_resp

            mem = get_active_membership(u, ticket.assigned_business_id)
            if not _employee_can_change_status(mem):
                return Response({"detail": "Not allowed."}, status=403)
            provider_start(ticket, u)
            ticket.refresh_from_db()
            return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

        return Response({"detail": "Only provider can start."}, status=403)

    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request, pk=None):
        ticket = self.get_object()
        u = request.user

        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot complete tickets."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if active_biz:
            locked_resp = _enforce_business_not_locked(active_biz)
            if locked_resp:
                return locked_resp

            mem = get_active_membership(u, active_biz.id)
            if mem and not _employee_can_change_status(mem) and getattr(active_biz, "owner_id", None) != u.id:
                return Response({"detail": "Not allowed."}, status=403)
            provider_complete(ticket, u)
            ticket.refresh_from_db()
            return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

        if role_is(u, "SBO"):
            business = Business.objects.filter(owner_id=u.id, is_active=True).order_by("id").first()
            if business:
                locked_resp = _enforce_business_not_locked(business)
                if locked_resp:
                    return locked_resp
            provider_complete(ticket, u)
            ticket.refresh_from_db()
            return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

        if role_is(u, "EMPLOYEE"):
            if not ticket.assigned_business_id:
                return Response({"detail": "Ticket not assigned to a business."}, status=400)

            biz = Business.objects.filter(id=ticket.assigned_business_id, is_active=True).first()
            if biz:
                locked_resp = _enforce_business_not_locked(biz)
                if locked_resp:
                    return locked_resp

            mem = get_active_membership(u, ticket.assigned_business_id)
            if not _employee_can_change_status(mem):
                return Response({"detail": "Not allowed."}, status=403)
            provider_complete(ticket, u)
            ticket.refresh_from_db()
            return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

        return Response({"detail": "Only provider can complete."}, status=403)

    @action(detail=True, methods=["post"], url_path="needs_quote")
    def needs_quote(self, request, pk=None):
        ticket = self.get_object()
        u = request.user
        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot set Needs Quote."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if active_biz:
            locked_resp = _enforce_business_not_locked(active_biz)
            if locked_resp:
                return locked_resp

        provider_set_needs_quote(ticket, u)
        ticket.refresh_from_db()
        return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="send_quote")
    def send_quote(self, request, pk=None):
        ticket = self.get_object()
        u = request.user
        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot send quotes."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if active_biz:
            locked_resp = _enforce_business_not_locked(active_biz)
            if locked_resp:
                return locked_resp

        quote_id = request.data.get("quote_id")
        if not quote_id:
            return Response({"detail": "quote_id required"}, status=400)

        try:
            quote = TicketQuote.objects.get(id=int(quote_id))
        except Exception:
            return Response({"detail": "Quote not found"}, status=404)

        provider_send_quote(ticket, quote, u)
        ticket.refresh_from_db()
        return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="approve_quote")
    def approve_quote(self, request, pk=None):
        ticket = self.get_object()
        u = request.user
        if not role_is(u, "CUSTOMER"):
            return Response({"detail": "Only customer can approve quote."}, status=403)

        quote_id = request.data.get("quote_id")
        if not quote_id:
            return Response({"detail": "quote_id required"}, status=400)

        try:
            quote = TicketQuote.objects.get(id=int(quote_id))
        except Exception:
            return Response({"detail": "Quote not found"}, status=404)

        if ticket.customer_id != u.id:
            return Response({"detail": "Not your ticket."}, status=403)

        customer_approve_quote(ticket, quote, u)
        ticket.refresh_from_db()
        return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="reject_quote")
    def reject_quote(self, request, pk=None):
        ticket = self.get_object()
        u = request.user
        if not role_is(u, "CUSTOMER"):
            return Response({"detail": "Only customer can reject quote."}, status=403)

        quote_id = request.data.get("quote_id")
        reason = request.data.get("reason", "") or ""

        if not quote_id:
            return Response({"detail": "quote_id required"}, status=400)

        try:
            quote = TicketQuote.objects.get(id=int(quote_id))
        except Exception:
            return Response({"detail": "Quote not found"}, status=404)

        if ticket.customer_id != u.id:
            return Response({"detail": "Not your ticket."}, status=403)

        customer_reject_quote(ticket, quote, u, reason=reason)
        ticket.refresh_from_db()
        return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="send_invoice")
    def send_invoice(self, request, pk=None):
        ticket = self.get_object()
        u = request.user
        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot send invoices."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if active_biz:
            locked_resp = _enforce_business_not_locked(active_biz)
            if locked_resp:
                return locked_resp

        invoice_id = request.data.get("invoice_id")
        if not invoice_id:
            return Response({"detail": "invoice_id required"}, status=400)

        try:
            inv = Invoice.objects.get(id=int(invoice_id))
        except Exception:
            return Response({"detail": "Invoice not found"}, status=404)

        if not _invoice_belongs_to_ticket(inv, ticket):
            return Response({"detail": "Invoice not found for this ticket"}, status=404)

        provider_send_invoice(ticket, inv, u)
        ticket.refresh_from_db()
        return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        u = request.user
        ticket = self.get_object()

        is_allowed_role = (
            role_is(u, "CUSTOMER", "SBO", "EMPLOYEE", "PM", "PROPERTY_MGR")
            or getattr(u, "is_superuser", False)
            or getattr(u, "is_platform_admin", False)
        )
        if not is_allowed_role:
            return Response({"detail": "Not allowed."}, status=403)

        if not role_is(u, "CUSTOMER"):
            active_biz = _get_active_business_from_request(request)
            if active_biz:
                locked_resp = _enforce_business_not_locked(active_biz)
                if locked_resp:
                    return locked_resp

        try:
            cancel_ticket(ticket, u, actor_is_customer=role_is(u, "CUSTOMER"))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        ticket.refresh_from_db()
        return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

    def destroy(self, request, *args, **kwargs):
        ticket = self.get_object()
        u = request.user

        if getattr(u, "is_superuser", False) or getattr(u, "is_platform_admin", False):
            return super().destroy(request, *args, **kwargs)

        if role_is(u, "CUSTOMER") and ticket.customer_id == u.id:
            if ticket.assigned_business_id is not None:
                return Response({"detail": "Cannot delete ticket after it is assigned."}, status=400)

            early = {"NEW"}
            if str(ticket.status or "").upper() not in early:
                return Response({"detail": "Cannot delete ticket after it progresses."}, status=400)

            return super().destroy(request, *args, **kwargs)

        return Response({"detail": "Not allowed."}, status=403)


class TicketMessageViewSet(viewsets.ModelViewSet):
    serializer_class = TicketMessageSerializer
    permission_classes = [IsAuthenticated, TicketParticipantRequired]

    def get_queryset(self):
        qs = TicketMessage.objects.all().order_by("created_at")
        ticket_id = self.request.query_params.get("ticket")
        if ticket_id:
            qs = qs.filter(ticket_id=ticket_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(sender=self.request.user, type=TicketMessage.MessageType.USER)


class TicketAttachmentViewSet(viewsets.ModelViewSet):
    serializer_class = TicketAttachmentSerializer
    permission_classes = [IsAuthenticated, TicketParticipantRequired]

    def get_queryset(self):
        qs = TicketAttachment.objects.all().order_by("-created_at")
        ticket_id = self.request.query_params.get("ticket")
        if ticket_id:
            qs = qs.filter(ticket_id=ticket_id)
        return qs

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)


class TicketQuoteViewSet(viewsets.ModelViewSet):
    serializer_class = TicketQuoteSerializer
    permission_classes = [IsAuthenticated, TicketParticipantRequired]

    def get_queryset(self):
        qs = TicketQuote.objects.all().order_by("-created_at")
        ticket_id = self.request.query_params.get("ticket")
        if ticket_id:
            qs = qs.filter(ticket_id=ticket_id)
        return qs

    def create(self, request, *args, **kwargs):
        if role_is(request.user, "CUSTOMER"):
            return Response({"detail": "Customers cannot create quotes."}, status=403)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated, TicketParticipantRequired]

    def get_queryset(self):
        qs = Invoice.objects.all().order_by("-created_at")
        ticket_id = self.request.query_params.get("ticket")
        if ticket_id and _invoice_has("ticket_id"):
            qs = qs.filter(ticket_id=ticket_id)
        elif ticket_id and _invoice_has("ticket"):
            qs = qs.filter(ticket_id=ticket_id)
        return qs

    def create(self, request, *args, **kwargs):
        if role_is(request.user, "CUSTOMER"):
            return Response({"detail": "Customers cannot create invoices."}, status=403)
        return super().create(request, *args, **kwargs)