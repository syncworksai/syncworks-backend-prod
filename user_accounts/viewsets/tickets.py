# backend/user_accounts/viewsets/tickets.py
from __future__ import annotations

from typing import Optional, Any, Dict
from decimal import Decimal

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
    Invoice,
    TicketViewEvent,
    DocumentTemplate,
    PlatformBillingProfile,
)

# ✅ Also support God Mode manual locks if they exist for this business
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
    """
    Uses permission flags.
    """
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


def _render_template_body(body: str, ctx: Dict[str, Any]) -> str:
    """
    Render DocumentTemplate.body using Django template syntax:
      "Taxi ride fee: {{amount}}"
    """
    engine = Engine(debug=False, autoescape=False)
    compiled = engine.from_string(body or "")
    return compiled.render(Context(ctx or {}))


# ----------------------------
# ✅ Billing lock enforcement helpers
# ----------------------------

LOCKED_DETAIL = "Business account is locked. Update billing or submit an unlock request."


def _locked_payload(business_id: int, lock_reason: str = "") -> Dict[str, Any]:
    return {
        "detail": LOCKED_DETAIL,
        "lock_reason": lock_reason or "",
        "business_id": business_id,
    }


def _get_lock_state_for_business(biz: Business) -> tuple[bool, str]:
    """
    Returns (is_locked, lock_reason) combining both:
      - PlatformBillingProfile (cash fees, card setup, billing enforcement)
      - BusinessAccessControl (God Mode manual locks)
    """
    # 1) Platform billing lock
    try:
        p = PlatformBillingProfile.objects.filter(business_id=biz.id).only("is_locked", "lock_reason").first()
        if p and bool(getattr(p, "is_locked", False)):
            return True, str(getattr(p, "lock_reason", "") or "")
    except Exception:
        pass

    # 2) God Mode access lock (optional table)
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
    # Match your existing error shape. Use 423 Locked (clear semantics).
    return Response(_locked_payload(biz.id, reason), status=423)


# ----------------------------
# Lite serializer for assignee dropdowns
# ----------------------------
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

    def get_queryset(self):
        """
        ✅ Provider rules:
          - /tickets/ is ASSIGNED ONLY (my business tickets)
          - /tickets/marketplace/ is MARKETPLACE ONLY (eligible queue)
        ✅ Customer rules:
          - /tickets/ is CUSTOMER'S OWN tickets (like previous orders)

        NOTE: We do NOT block read-only access here when locked.
        Lock enforcement is applied on provider actions (accept/start/complete/etc.).
        """
        u = self.request.user
        qs = Ticket.objects.all().order_by("-created_at")

        if getattr(u, "is_superuser", False) or getattr(u, "is_platform_admin", False):
            return qs

        if role_is(u, "CUSTOMER"):
            return qs.filter(customer_id=u.id)

        # Provider scope: assigned-only (marketplace handled by /tickets/marketplace/)
        active_biz = _get_active_business_from_request(self.request)
        if active_biz:
            return qs.filter(assigned_business_id=active_biz.id).distinct().order_by("-created_at")

        # Fallbacks if no X-Business-Id (conservative)
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

    # ----------------------------
    # Customer/provider utility
    # ----------------------------

    @action(detail=False, methods=["get"], url_path="my")
    def my(self, request):
        return Response(TicketSerializer(self.get_queryset(), many=True).data)

    @action(detail=False, methods=["get"], url_path="marketplace")
    def marketplace(self, request):
        """
        Provider-only: eligible marketplace queue for the ACTIVE business.
        """
        u = request.user
        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers do not have a marketplace queue."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if not active_biz:
            return Response({"detail": "X-Business-Id required."}, status=400)

        # ✅ Defense-in-depth: even if upstream middleware already blocks,
        # ensure this endpoint is consistent.
        locked_resp = _enforce_business_not_locked(active_biz)
        if locked_resp:
            return locked_resp

        qs = marketplace_tickets_for_business(active_biz)
        return Response(TicketSerializer(qs, many=True).data)

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
        return Response(TicketSerializer(ticket).data)

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

        return Response(TicketSerializer(ticket).data)

    # ----------------------------
    # ✅ Assignee helpers (for row quick actions)
    # ----------------------------

    @action(detail=False, methods=["get"], url_path="assignees")
    def assignees(self, request):
        """
        GET /tickets/assignees/?role=TECHNICIAN&q=jake
        Returns active BusinessMembers for the ACTIVE business.
        """
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

        # ✅ Role ordering: support both TECH and TECHNICIAN (your DB currently uses TECHNICIAN)
        role_priority = ["OWNER", "MANAGER", "DISPATCH", "TECHNICIAN", "TECH", "ACCOUNTING", "ADMIN"]
        whens = [When(role=r, then=Value(i)) for i, r in enumerate(role_priority)]
        qs = qs.annotate(_role_rank=Case(*whens, default=Value(999), output_field=IntegerField())).order_by(
            "_role_rank", "id"
        )[:200]

        return Response(BusinessMemberLiteSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"], url_path="assign_member")
    def assign_member(self, request, pk=None):
        """
        POST /tickets/:id/assign_member/  { "business_member_id": 123 }
        Sets ticket.assigned_member to the member's user.
        """
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

        # Ensure ticket is assigned to this business (marketplace accept flow may do this too)
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
        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=["post"], url_path="unassign_member")
    def unassign_member(self, request, pk=None):
        """
        POST /tickets/:id/unassign_member/
        Clears ticket.assigned_member.
        """
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
        return Response(TicketSerializer(ticket).data)

    # ----------------------------
    # ✅ NEW: Create invoice directly from Ticket + optional DocumentTemplate
    # ----------------------------
    @action(detail=True, methods=["post"], url_path="create_invoice")
    def create_invoice(self, request, pk=None):
        """
        POST /tickets/:id/create_invoice/
        Provider-only. Creates an Invoice attached to this ticket.
        """
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

        # Must belong to this business (assigned). If unassigned, attach it first.
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
        payment_method = (payload.get("payment_method") or Invoice.PaymentMethod.CARD).strip().upper()
        if payment_method not in {c[0] for c in Invoice.PaymentMethod.choices}:
            return Response({"detail": "Invalid payment_method."}, status=400)

        # If template is provided, render its body into notes
        if template_id:
            tpl = DocumentTemplate.objects.filter(id=template_id, business_id=active_biz.id, is_active=True).first()
            if not tpl:
                return Response({"detail": "Template not found for this business."}, status=404)

            ctx: Dict[str, Any] = {}
            if isinstance(context, dict):
                ctx.update(context)

            # helpful defaults
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

        inv = Invoice.objects.create(
            ticket=ticket,
            title=title,
            notes=notes,
            subtotal=subtotal,
            tax=tax,
            total=total,
            status=Invoice.Status.DRAFT,  # keep draft until send_invoice action
            due_date=due_date,
            payment_method=payment_method,
        )

        _system_msg(ticket, u, f"Invoice created (#{inv.id}).")
        return Response(InvoiceSerializer(inv).data, status=status.HTTP_201_CREATED)

    # ----------------------------
    # Marketplace UX events (provider only)
    # ----------------------------

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

        # Only meaningful for marketplace tickets
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

        # ✅ Policy choice:
        # We allow decline even when locked (it reduces spam / clears queue).
        # If you want it blocked too, uncomment the next 3 lines.
        # locked_resp = _enforce_business_not_locked(active_biz)
        # if locked_resp:
        #     return locked_resp

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

    # ----------------------------
    # Provider status actions
    # ----------------------------

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
            return Response(TicketSerializer(ticket).data)

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
            return Response(TicketSerializer(ticket).data)

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
            return Response(TicketSerializer(ticket).data)

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
            return Response(TicketSerializer(ticket).data)

        if role_is(u, "SBO"):
            business = Business.objects.filter(owner_id=u.id, is_active=True).order_by("id").first()
            if business:
                locked_resp = _enforce_business_not_locked(business)
                if locked_resp:
                    return locked_resp
            provider_start(ticket, u)
            return Response(TicketSerializer(ticket).data)

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
            return Response(TicketSerializer(ticket).data)

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
            return Response(TicketSerializer(ticket).data)

        if role_is(u, "SBO"):
            business = Business.objects.filter(owner_id=u.id, is_active=True).order_by("id").first()
            if business:
                locked_resp = _enforce_business_not_locked(business)
                if locked_resp:
                    return locked_resp
            provider_complete(ticket, u)
            return Response(TicketSerializer(ticket).data)

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
            return Response(TicketSerializer(ticket).data)

        return Response({"detail": "Only provider can complete."}, status=403)

    # ✅ Provider sets Needs Quote
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
        return Response(TicketSerializer(ticket).data)

    # ✅ Provider sends a quote (requires quote_id)
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
        return Response(TicketSerializer(ticket).data)

    # ✅ Customer approves quote
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
        return Response(TicketSerializer(ticket).data)

    # ✅ Customer rejects quote (does not cancel ticket)
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
        return Response(TicketSerializer(ticket).data)

    # ✅ Provider sends invoice (requires invoice_id)
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

        provider_send_invoice(ticket, inv, u)
        return Response(TicketSerializer(ticket).data)

    # ✅ Cancel rules enforced via service layer
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

        # ✅ Providers cannot cancel while locked (customer can still cancel their own early tickets)
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

        return Response(TicketSerializer(ticket).data)

    # ✅ Customer delete in early state only + only if unassigned
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
        if ticket_id:
            qs = qs.filter(ticket_id=ticket_id)
        return qs

    def create(self, request, *args, **kwargs):
        if role_is(request.user, "CUSTOMER"):
            return Response({"detail": "Customers cannot create invoices."}, status=403)
        return super().create(request, *args, **kwargs)