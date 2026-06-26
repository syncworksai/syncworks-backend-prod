from __future__ import annotations

from typing import Optional, Any, Dict
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q, Case, When, IntegerField, Value
from django.template import Context, Engine, TemplateSyntaxError
from django.utils import timezone

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
    ServiceCatalogItem,
    InvoiceLineItem,
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
    InvoiceLineItemSerializer,
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
    provider_schedule,
    provider_mark_en_route,
    provider_mark_on_site,
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


def _member_role(mem: Optional[BusinessMember]) -> str:
    return str(getattr(mem, "role", "") or "").upper()


def _employee_can_change_status(mem: Optional[BusinessMember]) -> bool:
    if not mem:
        return False
    return bool(getattr(mem, "can_assign_tickets", False) or getattr(mem, "can_close_tickets", False))


def _employee_can_assign(mem: Optional[BusinessMember]) -> bool:
    if not mem:
        return False
    return bool(getattr(mem, "can_assign_tickets", False))


def _employee_can_schedule(mem: Optional[BusinessMember]) -> bool:
    if not mem:
        return False
    return bool(
        getattr(mem, "can_manage_schedule", False)
        or _member_role(mem) in {"OWNER", "MANAGER", "DISPATCH", "ADMIN"}
    )


def _employee_is_assigned_tech(mem: Optional[BusinessMember], ticket: Ticket) -> bool:
    if not mem:
        return False
    return int(getattr(ticket, "assigned_member_id", 0) or 0) == int(getattr(mem, "user_id", 0) or 0)


def _employee_can_complete(mem: Optional[BusinessMember], ticket: Ticket) -> bool:
    if not mem:
        return False
    return bool(_employee_is_assigned_tech(mem, ticket) or getattr(mem, "can_close_tickets", False))


def _employee_can_manual_override(mem: Optional[BusinessMember]) -> bool:
    if not mem:
        return False
    return bool(
        getattr(mem, "can_manage_schedule", False)
        or getattr(mem, "can_assign_tickets", False)
        or getattr(mem, "can_close_tickets", False)
        or _member_role(mem) in {"OWNER", "MANAGER", "DISPATCH", "ADMIN"}
    )


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

    if "ticket" in fields:
        kwargs["ticket"] = ticket
    elif "ticket_id" in fields:
        kwargs["ticket_id"] = ticket.id

    if "title" in fields:
        kwargs["title"] = title
    elif "name" in fields:
        kwargs["name"] = title

    if "notes" in fields:
        kwargs["notes"] = notes
    elif "memo" in fields:
        kwargs["memo"] = notes

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

    if "business" in fields:
        kwargs["business"] = active_biz
    elif "business_id" in fields:
        kwargs["business_id"] = active_biz.id

    if "created_by" in fields:
        kwargs["created_by"] = actor_user
    elif "created_by_id" in fields and getattr(actor_user, "id", None):
        kwargs["created_by_id"] = actor_user.id

    if "kind" in fields:
        kwargs["kind"] = "JOB"
    if "status" in fields:
        if hasattr(Invoice, "Status") and hasattr(Invoice.Status, "DRAFT"):
            kwargs["status"] = Invoice.Status.DRAFT
        else:
            kwargs["status"] = "DRAFT"
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
    return False


def _get_or_create_ticket_draft_invoice(ticket: Ticket, active_biz: Business, actor_user) -> Invoice:
    existing = (
        Invoice.objects.filter(ticket_id=ticket.id, status=Invoice.Status.DRAFT)
        .order_by("-created_at")
        .first()
    )
    if existing:
        return existing

    title = f"Invoice for Ticket #{ticket.id}"
    kwargs = _build_invoice_create_kwargs(
        ticket=ticket,
        active_biz=active_biz,
        actor_user=actor_user,
        title=title,
        notes="",
        subtotal=Decimal("0.00"),
        tax=Decimal("0.00"),
        total=Decimal("0.00"),
        due_date=None,
        payment_method=Invoice.PaymentMethod.CARD,
    )
    return Invoice.objects.create(**kwargs)


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


class CatalogLineAddSerializer(serializers.Serializer):
    catalog_item_id = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=Decimal("1.00"))
    due_date = serializers.DateField(required=False, allow_null=True)
    payment_method = serializers.ChoiceField(
        choices=[Invoice.PaymentMethod.CARD, Invoice.PaymentMethod.CASH, Invoice.PaymentMethod.OTHER],
        required=False,
    )

    def validate_quantity(self, v):
        if Decimal(str(v)) <= 0:
            raise serializers.ValidationError("quantity must be greater than 0.")
        return v


class TicketManualStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Ticket.Status.choices)


class TicketViewSet(viewsets.ModelViewSet):
    serializer_class = TicketSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def _base_queryset(self):
        return (
            Ticket.objects.all()
            .select_related("category", "assigned_business", "assigned_member", "customer", "service_request")
            .order_by("-created_at")
        )

    def _apply_archive_filter(self, qs):
        archived = self.request.query_params.get("archived")
        if archived is None:
            return qs

        truthy = str(archived).strip().lower() in {"1", "true", "yes", "y", "on"}
        if truthy:
            return qs.filter(archived_at__isnull=False)
        return qs.filter(archived_at__isnull=True)

    def _eligible_marketplace_ticket_ids_for_business(self, business: Business | None) -> list[int]:
        if not business:
            return []
        try:
            return list(marketplace_tickets_for_business(business).values_list("id", flat=True))
        except Exception:
            return []

    def _provider_visible_queryset_for_business(self, qs, business: Business | None):
        if not business:
            return qs.none()

        marketplace_ids = self._eligible_marketplace_ticket_ids_for_business(business)
        filters = Q(assigned_business_id=business.id)
        if marketplace_ids:
            filters |= Q(id__in=marketplace_ids)
        return qs.filter(filters).distinct().order_by("-created_at")

    def _employee_business_ids(self, user) -> list[int]:
        return list(
            BusinessMember.objects.filter(user_id=user.id, is_active=True).values_list("business_id", flat=True)
        )

    def get_queryset(self):
        u = self.request.user
        qs = self._apply_archive_filter(self._base_queryset())
        action = getattr(self, "action", None)

        if getattr(u, "is_superuser", False) or getattr(u, "is_platform_admin", False):
            return qs

        if role_is(u, "CUSTOMER"):
            return qs.filter(customer_id=u.id).distinct().order_by("-created_at")

        if action == "marketplace":
            return qs.none()

        provider_list_actions = {None, "list", "my"}
        provider_detailish_actions = {
            "retrieve",
            "partial_update",
            "update",
            "destroy",
            "mark_viewed",
            "decline_marketplace",
            "accept",
            "schedule",
            "en_route",
            "on_site",
            "start",
            "complete",
            "set_status",
            "needs_quote",
            "send_quote",
            "approve_quote",
            "reject_quote",
            "send_invoice",
            "cancel",
            "eligible_providers",
            "assign_sbo",
            "assignees",
            "assign_member",
            "unassign_member",
            "create_invoice",
            "add_catalog_item",
            "invoice_lines",
            "remove_catalog_line",
            "archive",
            "unarchive",
        }

        active_biz = _get_active_business_from_request(self.request)

        if role_is(u, "SBO"):
            business = active_biz or Business.objects.filter(owner_id=u.id, is_active=True).order_by("id").first()
            if not business:
                return qs.none()

            if action in provider_list_actions:
                return qs.filter(assigned_business_id=business.id).distinct().order_by("-created_at")

            if action in provider_detailish_actions:
                return self._provider_visible_queryset_for_business(qs, business)

            return qs.filter(assigned_business_id=business.id).distinct().order_by("-created_at")

        if role_is(u, "EMPLOYEE", "PM", "PROPERTY_MGR"):
            if active_biz:
                if action in provider_list_actions:
                    return qs.filter(assigned_business_id=active_biz.id).distinct().order_by("-created_at")

                if action in provider_detailish_actions:
                    return self._provider_visible_queryset_for_business(qs, active_biz)

                return qs.filter(assigned_business_id=active_biz.id).distinct().order_by("-created_at")

            biz_ids = self._employee_business_ids(u)
            if not biz_ids:
                return qs.none()

            if action in provider_list_actions:
                return qs.filter(assigned_business_id__in=biz_ids).distinct().order_by("-created_at")

            if action in provider_detailish_actions:
                union_ids: set[int] = set(qs.filter(assigned_business_id__in=biz_ids).values_list("id", flat=True))
                for biz in Business.objects.filter(id__in=biz_ids, is_active=True):
                    union_ids.update(self._eligible_marketplace_ticket_ids_for_business(biz))
                if not union_ids:
                    return qs.none()
                return qs.filter(id__in=list(union_ids)).distinct().order_by("-created_at")

            return qs.filter(assigned_business_id__in=biz_ids).distinct().order_by("-created_at")

        return qs.none()

    def perform_create(self, serializer):
        serializer.save(customer=self.request.user)

    @action(detail=False, methods=["get"], url_path="my")
    def my(self, request):
        return Response(TicketSerializer(self.get_queryset(), many=True, context=self.get_serializer_context()).data)

    @action(detail=False, methods=["get"], url_path="kpi-summary")
    def kpi_summary(self, request):
        u = request.user
        if not (getattr(u, "is_superuser", False) or getattr(u, "is_platform_admin", False)):
            return Response({"detail": "Not authorized."}, status=403)

        qs = Ticket.objects.all()

        return Response(
            {
                "tickets_total": qs.count(),
                "tickets_direct": qs.filter(is_marketplace=False).count(),
                "tickets_marketplace": qs.filter(is_marketplace=True).count(),
                "tickets_archived": qs.filter(archived_at__isnull=False).count(),
                "tickets_active": qs.filter(archived_at__isnull=True).count(),
                "completed_direct": qs.filter(is_marketplace=False, status=Ticket.Status.COMPLETED).count(),
                "completed_marketplace": qs.filter(is_marketplace=True, status=Ticket.Status.COMPLETED).count(),
                "paid_direct": qs.filter(is_marketplace=False, status=Ticket.Status.PAID).count(),
                "paid_marketplace": qs.filter(is_marketplace=True, status=Ticket.Status.PAID).count(),
            }
        )

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
        serializer_context = self.get_serializer_context()
        serializer_context["match_business"] = active_biz
        return Response(
            TicketSerializer(qs, many=True, context=serializer_context).data
        )

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, pk=None):
        ticket = self.get_object()
        u = request.user

        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot archive tickets."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if active_biz:
            locked_resp = _enforce_business_not_locked(active_biz)
            if locked_resp:
                return locked_resp

            if ticket.assigned_business_id and ticket.assigned_business_id != active_biz.id:
                return Response({"detail": "Ticket belongs to a different business."}, status=403)

        if ticket.archived_at:
            return Response(
                {
                    "detail": "Ticket is already archived.",
                    "ticket": TicketSerializer(ticket, context=self.get_serializer_context()).data,
                },
                status=status.HTTP_200_OK,
            )

        ticket.archived_at = timezone.now()
        ticket.archived_by = u
        ticket.save(update_fields=["archived_at", "archived_by"])

        _system_msg(ticket, u, "Ticket archived.")
        ticket.refresh_from_db()
        return Response(
            {
                "detail": "Ticket archived.",
                "ticket": TicketSerializer(ticket, context=self.get_serializer_context()).data,
            }
        )

    @action(detail=True, methods=["post"], url_path="unarchive")
    def unarchive(self, request, pk=None):
        ticket = self.get_object()
        u = request.user

        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot unarchive tickets."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if active_biz:
            locked_resp = _enforce_business_not_locked(active_biz)
            if locked_resp:
                return locked_resp

            if ticket.assigned_business_id and ticket.assigned_business_id != active_biz.id:
                return Response({"detail": "Ticket belongs to a different business."}, status=403)

        if not ticket.archived_at:
            return Response(
                {
                    "detail": "Ticket is already active.",
                    "ticket": TicketSerializer(ticket, context=self.get_serializer_context()).data,
                },
                status=status.HTTP_200_OK,
            )

        ticket.archived_at = None
        ticket.archived_by = None
        ticket.save(update_fields=["archived_at", "archived_by"])

        _system_msg(ticket, u, "Ticket restored from archive.")
        ticket.refresh_from_db()
        return Response(
            {
                "detail": "Ticket restored.",
                "ticket": TicketSerializer(ticket, context=self.get_serializer_context()).data,
            }
        )

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

        return Response(
            [
                {
                    "id": m.id,
                    "role": m.role,
                    "is_active": m.is_active,
                    "user_id": m.user_id,
                    "user_email": getattr(m.user, "email", "") or "",
                    "user_name": (
                        (
                            (getattr(m.user, "first_name", "") or "").strip()
                            + " "
                            + (getattr(m.user, "last_name", "") or "").strip()
                        ).strip()
                        or (getattr(m.user, "email", "") or "")
                    ),
                    "can_manage_schedule": bool(getattr(m, "can_manage_schedule", False)),
                    "can_assign_tickets": bool(getattr(m, "can_assign_tickets", False)),
                    "can_close_tickets": bool(getattr(m, "can_close_tickets", False)),
                }
                for m in qs
            ]
        )

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
        if str(ticket.status or "").upper() == Ticket.Status.NEW and ticket.assigned_business_id == active_biz.id:
            ticket.status = Ticket.Status.ASSIGNED
            ticket.assigned_at = ticket.assigned_at or timezone.now()
            ticket.save(update_fields=["assigned_member_id", "status", "assigned_at"])
        else:
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

    @action(detail=True, methods=["post"], url_path="set-status")
    def set_status(self, request, pk=None):
        u = request.user
        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot manually change ticket status."}, status=403)

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
        is_owner = getattr(active_biz, "owner_id", None) == u.id
        if mem and not _employee_can_manual_override(mem) and not is_owner:
            return Response({"detail": "Not allowed."}, status=403)

        ser = TicketManualStatusSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        new_status = str(ser.validated_data["status"] or "").upper()

        now = timezone.now()
        update_fields = ["status"]

        ticket.status = new_status

        if new_status == Ticket.Status.ASSIGNED:
            if not ticket.assigned_at:
                ticket.assigned_at = now
                update_fields.append("assigned_at")

        elif new_status == Ticket.Status.ACCEPTED:
            if not ticket.accepted_at:
                ticket.accepted_at = now
                update_fields.append("accepted_at")

        elif new_status == Ticket.Status.SCHEDULED:
            if not ticket.scheduled_at:
                ticket.scheduled_at = now
                update_fields.append("scheduled_at")

        elif new_status == Ticket.Status.EN_ROUTE:
            if not ticket.en_route_at:
                ticket.en_route_at = now
                update_fields.append("en_route_at")

        elif new_status == Ticket.Status.ON_SITE:
            if not ticket.on_site_at:
                ticket.on_site_at = now
                update_fields.append("on_site_at")

        elif new_status == Ticket.Status.IN_PROGRESS:
            if not ticket.started_at:
                ticket.started_at = now
                update_fields.append("started_at")

        elif new_status == Ticket.Status.AWAITING_APPROVAL:
            if not ticket.awaiting_approval_at:
                ticket.awaiting_approval_at = now
                update_fields.append("awaiting_approval_at")

        elif new_status == Ticket.Status.COMPLETED:
            if not ticket.completed_at:
                ticket.completed_at = now
                update_fields.append("completed_at")

        elif new_status == Ticket.Status.INVOICED:
            if not ticket.invoiced_at:
                ticket.invoiced_at = now
                update_fields.append("invoiced_at")

        elif new_status == Ticket.Status.PAID:
            if not ticket.paid_at:
                ticket.paid_at = now
                update_fields.append("paid_at")

        elif new_status == Ticket.Status.CANCELLED:
            if not ticket.cancelled_at:
                ticket.cancelled_at = now
                update_fields.append("cancelled_at")

        elif new_status == Ticket.Status.CLOSED:
            if not ticket.closed_at:
                ticket.closed_at = now
                update_fields.append("closed_at")

        ticket.save(update_fields=update_fields)
        _system_msg(ticket, u, f"Manual status override: {new_status}.")
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

    @action(detail=True, methods=["post"], url_path="add-catalog-item")
    def add_catalog_item(self, request, pk=None):
        u = request.user
        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot add catalog items."}, status=403)

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

        ser = CatalogLineAddSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        item = ServiceCatalogItem.objects.filter(
            id=int(data["catalog_item_id"]),
            business_id=active_biz.id,
        ).first()
        if not item:
            return Response({"detail": "Catalog item not found for this business."}, status=404)

        invoice = _get_or_create_ticket_draft_invoice(ticket, active_biz, u)
        qty_to_add = Decimal(str(data.get("quantity") or "1.00"))

        matching_lines = list(
            InvoiceLineItem.objects.filter(
                invoice_id=invoice.id,
                catalog_item_id=item.id,
            ).order_by("id")
        )

        if matching_lines:
            master = matching_lines[0]
            merged_qty = Decimal("0.00")

            for li in matching_lines:
                merged_qty += Decimal(str(li.quantity or "0.00"))

            merged_qty += qty_to_add

            master.quantity = merged_qty
            master.unit_price = item.unit_price
            master.unit_cost = item.unit_cost
            master.description = item.description or ""
            master.item_type = item.item_type or InvoiceLineItem.ItemType.CUSTOM
            master.unit_label = item.unit_label or ""
            master.name = item.name
            master.save()

            for extra in matching_lines[1:]:
                extra.delete()

            line = master
        else:
            max_sort = (
                InvoiceLineItem.objects.filter(invoice_id=invoice.id)
                .order_by("-sort_order")
                .values_list("sort_order", flat=True)
                .first()
                or 0
            )

            line = InvoiceLineItem.objects.create(
                invoice=invoice,
                catalog_item=item,
                name=item.name,
                description=item.description or "",
                item_type=item.item_type or InvoiceLineItem.ItemType.CUSTOM,
                unit_label=item.unit_label or "",
                quantity=qty_to_add,
                unit_price=item.unit_price,
                unit_cost=item.unit_cost,
                sort_order=max_sort + 10,
            )

        if data.get("due_date") is not None:
            invoice.due_date = data.get("due_date")
        if data.get("payment_method"):
            invoice.payment_method = data["payment_method"]

        invoice.recompute_totals_from_lines()
        invoice.save()

        ticket.total_amount_cents = _money_to_cents(invoice.total)
        ticket.payment_method = invoice.payment_method or Ticket.PaymentMethod.CARD
        ticket.save(update_fields=["total_amount_cents", "payment_method"])

        _system_msg(ticket, u, f"Added catalog item '{item.name}' to invoice draft.")
        return Response(
            {
                "invoice": InvoiceSerializer(invoice).data,
                "line_item": InvoiceLineItemSerializer(line).data,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="invoice-lines")
    def invoice_lines(self, request, pk=None):
        u = request.user
        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot view invoice draft lines here."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if not active_biz:
            return Response({"detail": "X-Business-Id required."}, status=400)

        ticket = self.get_object()
        invoice = (
            Invoice.objects.filter(ticket_id=ticket.id)
            .order_by(
                Case(
                    When(status=Invoice.Status.DRAFT, then=Value(0)),
                    When(status=Invoice.Status.SENT, then=Value(1)),
                    When(status=Invoice.Status.PAID, then=Value(2)),
                    default=Value(9),
                    output_field=IntegerField(),
                ),
                "-created_at",
            )
            .first()
        )
        if not invoice:
            return Response({"invoice": None, "results": []})

        lines = InvoiceLineItem.objects.filter(invoice_id=invoice.id).order_by("sort_order", "id")
        return Response(
            {
                "invoice": InvoiceSerializer(invoice).data,
                "results": InvoiceLineItemSerializer(lines, many=True).data,
            }
        )

    @action(detail=True, methods=["post"], url_path="remove-catalog-line")
    def remove_catalog_line(self, request, pk=None):
        u = request.user
        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot remove catalog items."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if not active_biz:
            return Response({"detail": "X-Business-Id required."}, status=400)

        locked_resp = _enforce_business_not_locked(active_biz)
        if locked_resp:
            return locked_resp

        ticket = self.get_object()

        catalog_item_id = request.data.get("catalog_item_id")
        qty_to_remove = Decimal(str(request.data.get("quantity") or "1.00"))

        if not catalog_item_id:
            return Response({"detail": "catalog_item_id required"}, status=400)

        if qty_to_remove <= 0:
            return Response({"detail": "quantity must be > 0"}, status=400)

        invoice = (
            Invoice.objects.filter(ticket_id=ticket.id, status=Invoice.Status.DRAFT)
            .order_by("-created_at")
            .first()
        )
        if not invoice:
            return Response({"detail": "No draft invoice found."}, status=404)

        matching_lines = list(
            InvoiceLineItem.objects.filter(
                invoice_id=invoice.id,
                catalog_item_id=int(catalog_item_id),
            ).order_by("id")
        )
        if not matching_lines:
            return Response({"detail": "Line item not found."}, status=404)

        master = matching_lines[0]
        merged_qty = Decimal("0.00")
        for li in matching_lines:
            merged_qty += Decimal(str(li.quantity or "0.00"))

        master.quantity = merged_qty
        master.save()

        for extra in matching_lines[1:]:
            extra.delete()

        master.quantity = Decimal(str(master.quantity or "0.00")) - qty_to_remove

        removed_name = master.name

        if master.quantity <= 0:
            master.delete()
        else:
            master.save()

        invoice.recompute_totals_from_lines()
        invoice.save()

        ticket.total_amount_cents = _money_to_cents(invoice.total)
        ticket.payment_method = invoice.payment_method or Ticket.PaymentMethod.CARD
        ticket.save(update_fields=["total_amount_cents", "payment_method"])

        _system_msg(ticket, u, f"Removed quantity from '{removed_name}'.")
        return Response({"invoice": InvoiceSerializer(invoice).data, "ok": True})

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

        if str(ticket.status or "").upper() != Ticket.Status.NEW:
            return Response({"detail": "Only NEW marketplace tickets can be declined."}, status=400)

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

            try:
                provider_accept(ticket, u)
            except ValueError as e:
                return Response({"detail": str(e)}, status=400)

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

            try:
                provider_accept(ticket, u)
            except ValueError as e:
                return Response({"detail": str(e)}, status=400)

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

            try:
                provider_accept(ticket, u)
            except ValueError as e:
                return Response({"detail": str(e)}, status=400)

            ticket.refresh_from_db()
            return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

        return Response({"detail": "Only provider can accept."}, status=403)

    @action(detail=True, methods=["post"], url_path="schedule")
    def schedule(self, request, pk=None):
        ticket = self.get_object()
        u = request.user

        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot schedule tickets."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if not active_biz:
            return Response({"detail": "X-Business-Id required."}, status=400)

        locked_resp = _enforce_business_not_locked(active_biz)
        if locked_resp:
            return locked_resp

        if not ticket.assigned_business_id:
            assign_ticket_to_business(ticket, active_biz)
        elif ticket.assigned_business_id != active_biz.id:
            return Response({"detail": "Ticket is assigned to a different business."}, status=403)

        mem = get_active_membership(u, active_biz.id)
        if mem and not _employee_can_schedule(mem) and getattr(active_biz, "owner_id", None) != u.id:
            return Response({"detail": "Not allowed."}, status=403)

        try:
            provider_schedule(ticket, u, mem)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        except Exception as e:
            return Response({"detail": str(e)}, status=403)

        ticket.refresh_from_db()
        return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="en-route")
    def en_route(self, request, pk=None):
        ticket = self.get_object()
        u = request.user

        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot mark En Route."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if not active_biz:
            return Response({"detail": "X-Business-Id required."}, status=400)

        locked_resp = _enforce_business_not_locked(active_biz)
        if locked_resp:
            return locked_resp

        if ticket.assigned_business_id != active_biz.id:
            return Response({"detail": "Ticket is assigned to a different business."}, status=403)

        mem = get_active_membership(u, active_biz.id)
        if mem and not _employee_is_assigned_tech(mem, ticket) and getattr(active_biz, "owner_id", None) != u.id:
            return Response({"detail": "Only the assigned technician can mark En Route."}, status=403)

        try:
            provider_mark_en_route(ticket, u, mem)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        except Exception as e:
            return Response({"detail": str(e)}, status=403)

        ticket.refresh_from_db()
        return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="on-site")
    def on_site(self, request, pk=None):
        ticket = self.get_object()
        u = request.user

        if role_is(u, "CUSTOMER"):
            return Response({"detail": "Customers cannot mark On Site."}, status=403)

        active_biz = _get_active_business_from_request(request)
        if not active_biz:
            return Response({"detail": "X-Business-Id required."}, status=400)

        locked_resp = _enforce_business_not_locked(active_biz)
        if locked_resp:
            return locked_resp

        if ticket.assigned_business_id != active_biz.id:
            return Response({"detail": "Ticket is assigned to a different business."}, status=403)

        mem = get_active_membership(u, active_biz.id)
        if mem and not _employee_is_assigned_tech(mem, ticket) and getattr(active_biz, "owner_id", None) != u.id:
            return Response({"detail": "Only the assigned technician can mark On Site."}, status=403)

        try:
            provider_mark_on_site(ticket, u, mem)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        except Exception as e:
            return Response({"detail": str(e)}, status=403)

        ticket.refresh_from_db()
        return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

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
            is_owner = getattr(active_biz, "owner_id", None) == u.id
            if mem and not _employee_is_assigned_tech(mem, ticket) and not is_owner:
                return Response({"detail": "Only the assigned technician can start work."}, status=403)

            try:
                provider_start(ticket, u, mem if not is_owner else None)
            except ValueError as e:
                return Response({"detail": str(e)}, status=400)
            except Exception as e:
                return Response({"detail": str(e)}, status=403)

            ticket.refresh_from_db()
            return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

        if role_is(u, "SBO"):
            business = Business.objects.filter(owner_id=u.id, is_active=True).order_by("id").first()
            if business:
                locked_resp = _enforce_business_not_locked(business)
                if locked_resp:
                    return locked_resp
            try:
                provider_start(ticket, u, None)
            except ValueError as e:
                return Response({"detail": str(e)}, status=400)

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
            if not _employee_is_assigned_tech(mem, ticket):
                return Response({"detail": "Only the assigned technician can start work."}, status=403)

            try:
                provider_start(ticket, u, mem)
            except ValueError as e:
                return Response({"detail": str(e)}, status=400)

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
            is_owner = getattr(active_biz, "owner_id", None) == u.id
            if mem and not _employee_can_complete(mem, ticket) and not is_owner:
                return Response({"detail": "Not allowed."}, status=403)

            try:
                provider_complete(ticket, u, mem if not is_owner else None)
            except ValueError as e:
                return Response({"detail": str(e)}, status=400)
            except Exception as e:
                return Response({"detail": str(e)}, status=403)

            ticket.refresh_from_db()
            return Response(TicketSerializer(ticket, context=self.get_serializer_context()).data)

        if role_is(u, "SBO"):
            business = Business.objects.filter(owner_id=u.id, is_active=True).order_by("id").first()
            if business:
                locked_resp = _enforce_business_not_locked(business)
                if locked_resp:
                    return locked_resp

            try:
                provider_complete(ticket, u, None)
            except ValueError as e:
                return Response({"detail": str(e)}, status=400)

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
            if not _employee_can_complete(mem, ticket):
                return Response({"detail": "Not allowed."}, status=403)

            try:
                provider_complete(ticket, u, mem)
            except ValueError as e:
                return Response({"detail": str(e)}, status=400)

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

        try:
            provider_set_needs_quote(ticket, u)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

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

        try:
            provider_send_quote(ticket, quote, u)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

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

        try:
            customer_approve_quote(ticket, quote, u)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

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

        try:
            customer_reject_quote(ticket, quote, u, reason=reason)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

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

        try:
            provider_send_invoice(ticket, inv, u)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

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
        qs = Invoice.objects.all().prefetch_related("line_items").order_by("-created_at")
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