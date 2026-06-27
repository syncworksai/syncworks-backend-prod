from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import (
    Business,
    BusinessMember,
    Ticket,
    TicketConversationReadState,
    TicketMessage,
)
from user_accounts.serializers.tickets import TicketMessageSerializer


LEADERSHIP_ROLES = {"OWNER", "MANAGER", "DISPATCH", "ACCOUNTING", "ADMIN"}


def _business_id(request):
    raw = (
        request.headers.get("X-Business-Id")
        or request.META.get("HTTP_X_BUSINESS_ID")
        or request.query_params.get("business")
    )
    try:
        return int(raw) if raw else None
    except Exception:
        return None


def _business_context(request):
    business_id = _business_id(request)
    if not business_id:
        raise ValidationError({"business": "X-Business-Id is required for the Business Inbox."})

    business = get_object_or_404(Business, id=business_id, is_active=True)
    user = request.user

    if getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False):
        return business, None, True

    if business.owner_id == user.id:
        return business, None, True

    membership = BusinessMember.objects.filter(
        business=business,
        user=user,
        is_active=True,
    ).first()
    if not membership:
        raise PermissionDenied("You do not have access to this Business Inbox.")

    role = str(getattr(membership, "role", "") or "").upper()
    has_oversight = role in LEADERSHIP_ROLES or bool(
        getattr(membership, "can_assign_tickets", False)
        or getattr(membership, "can_close_tickets", False)
        or getattr(membership, "can_manage_schedule", False)
    )
    return business, membership, has_oversight


def _scope(request):
    raw = str(request.query_params.get("scope") or "PERSONAL").strip().upper()
    if raw not in {"PERSONAL", "BUSINESS"}:
        raise ValidationError({"scope": "This endpoint currently supports PERSONAL or BUSINESS."})
    return raw


def _visible_tickets(request, scope):
    user = request.user
    base = (
        Ticket.objects.select_related(
            "category",
            "customer",
            "assigned_business",
            "assigned_member",
            "service_request",
        )
        .prefetch_related("messages")
        .order_by("-created_at")
    )

    if getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False):
        if scope == "PERSONAL":
            return base.filter(customer=user)
        business, _, _ = _business_context(request)
        return base.filter(assigned_business=business)

    if scope == "PERSONAL":
        return base.filter(customer=user)

    business, membership, has_oversight = _business_context(request)
    qs = base.filter(assigned_business=business)

    if has_oversight:
        return qs

    return qs.filter(assigned_member=user)


def _display_name(user):
    if not user:
        return ""
    full = f"{getattr(user, 'first_name', '') or ''} {getattr(user, 'last_name', '') or ''}".strip()
    return full or getattr(user, "email", "") or getattr(user, "username", "") or f"User #{user.id}"


def _read_state_for(user, ticket, scope):
    return TicketConversationReadState.objects.filter(
        user=user,
        ticket=ticket,
        scope=scope,
    ).first()


def _unread_count(user, ticket, scope):
    state = _read_state_for(user, ticket, scope)
    qs = ticket.messages.exclude(sender=user)
    if state and state.last_read_message_id:
        qs = qs.filter(id__gt=state.last_read_message_id)
    return qs.count()


def _mark_read(user, ticket, scope):
    latest = ticket.messages.order_by("-created_at", "-id").first()
    state, _ = TicketConversationReadState.objects.get_or_create(
        user=user,
        ticket=ticket,
        scope=scope,
    )
    state.last_read_message = latest
    state.last_read_at = timezone.now()
    state.needs_attention = False
    state.attention_reason = ""
    state.save(update_fields=[
        "last_read_message",
        "last_read_at",
        "needs_attention",
        "attention_reason",
        "updated_at",
    ])
    return state


def _thread_payload(ticket, scope, user=None):
    latest = ticket.messages.order_by("-created_at", "-id").first()
    category_name = ""
    category_path = ""
    if ticket.category_id and ticket.category:
        category_name = ticket.category.name or ""
        category_path = category_name
        current = ticket.category
        names = []
        guard = 0
        while current is not None and guard < 20:
            names.append(current.name)
            current = getattr(current, "parent", None)
            guard += 1
        if names:
            category_path = " → ".join(reversed(names))

    unread_count = _unread_count(user, ticket, scope) if user else 0
    state = _read_state_for(user, ticket, scope) if user else None

    return {
        "id": ticket.id,
        "thread_key": f"ticket:{ticket.id}",
        "scope": scope,
        "source_type": "TICKET",
        "source_id": ticket.id,
        "ticket_code": ticket.ticket_code,
        "subject": category_path or category_name or f"Ticket #{ticket.id}",
        "status": ticket.status,
        "is_marketplace": bool(ticket.is_marketplace),
        "is_archived": bool(ticket.archived_at),
        "customer": {
            "id": ticket.customer_id,
            "name": _display_name(ticket.customer),
        },
        "business": {
            "id": ticket.assigned_business_id,
            "name": getattr(ticket.assigned_business, "name", "") if ticket.assigned_business_id else "",
        },
        "assigned_member": {
            "id": ticket.assigned_member_id,
            "name": _display_name(ticket.assigned_member),
        } if ticket.assigned_member_id else None,
        "latest_message": {
            "id": latest.id,
            "body": latest.body,
            "type": latest.type,
            "sender_id": latest.sender_id,
            "sender_name": _display_name(latest.sender),
            "created_at": latest.created_at.isoformat() if latest.created_at else None,
        } if latest else None,
        "message_count": ticket.messages.count(),
        "unread_count": unread_count,
        "is_unread": unread_count > 0,
        "pinned": bool(getattr(state, "pinned", False)),
        "muted": bool(getattr(state, "muted", False)),
        "needs_attention": bool(getattr(state, "needs_attention", False)),
        "attention_reason": getattr(state, "attention_reason", "") if state else "",
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": (
            latest.created_at.isoformat()
            if latest and latest.created_at
            else ticket.created_at.isoformat() if ticket.created_at else None
        ),
        "automation": {
            "created_automatically": True,
            "categorized_automatically": True,
            "routing": (
                "PERSONAL_OWNER"
                if scope == "PERSONAL"
                else "BUSINESS_OVERSIGHT_OR_ASSIGNEE"
            ),
        },
    }


class TicketConversationListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        scope = _scope(request)
        qs = _visible_tickets(request, scope)

        status_value = str(request.query_params.get("status") or "").strip().upper()
        archived = str(request.query_params.get("archived") or "false").strip().lower()
        query = str(request.query_params.get("q") or "").strip()

        if status_value:
            qs = qs.filter(status=status_value)
        if archived in {"1", "true", "yes"}:
            qs = qs.filter(archived_at__isnull=False)
        elif archived not in {"all", "*"}:
            qs = qs.filter(archived_at__isnull=True)
        if query:
            qs = qs.filter(
                Q(category__name__icontains=query)
                | Q(service_address__icontains=query)
                | Q(service_zip__icontains=query)
                | Q(messages__body__icontains=query)
            ).distinct()

        rows = [_thread_payload(ticket, scope, request.user) for ticket in qs[:200]]
        rows.sort(key=lambda row: (not row["pinned"], not row["is_unread"], row["updated_at"] or ""))
        unread_total = sum(int(row["unread_count"] or 0) for row in rows)
        return Response({
            "scope": scope,
            "count": qs.count(),
            "unread_total": unread_total,
            "results": rows,
            "inbox_rules": {
                "personal_isolated_from_business": True,
                "outside_spam_allowed": False,
                "ads_allowed": False,
                "automatic_ticket_threads": True,
            },
        })


class TicketConversationMessagesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _ticket(self, request, ticket_id):
        scope = _scope(request)
        ticket = get_object_or_404(_visible_tickets(request, scope), id=ticket_id)
        return scope, ticket

    def get(self, request, ticket_id):
        scope, ticket = self._ticket(request, ticket_id)
        messages = ticket.messages.select_related("sender").order_by("created_at", "id")
        _mark_read(request.user, ticket, scope)
        return Response({
            "thread": _thread_payload(ticket, scope, request.user),
            "count": messages.count(),
            "results": TicketMessageSerializer(messages, many=True).data,
        })

    def post(self, request, ticket_id):
        scope, ticket = self._ticket(request, ticket_id)
        body = str((request.data or {}).get("body") or "").strip()
        if not body:
            raise ValidationError({"body": "Message body is required."})

        message = TicketMessage.objects.create(
            ticket=ticket,
            sender=request.user,
            body=body,
            type=TicketMessage.MessageType.USER,
        )

        return Response(
            {
                "thread": _thread_payload(ticket, scope, request.user),
                "message": TicketMessageSerializer(message).data,
                "delivery": {
                    "internal_inbox": "DELIVERED",
                    "email_notification": "QUEUED_BY_PREFERENCE",
                    "sms_notification": "PAID_ADDON_ONLY",
                },
            },
            status=201,
        )
