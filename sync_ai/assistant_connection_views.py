from __future__ import annotations

from django.db.models import Max, Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from personal_calendar.connection_store import list_connections, public_connection
from user_accounts.models import Ticket, TicketConversationReadState

from .jarvis_product import load_profile, save_profile, settings_for
from .location_intelligence import geocode_address


CLOSED_TICKET_STATUSES = {
    Ticket.Status.COMPLETED,
    Ticket.Status.PAID,
    Ticket.Status.CANCELLED,
    Ticket.Status.CLOSED,
}


def _personal_ticket_rows(user):
    tickets = (
        Ticket.objects.filter(customer=user, archived_at__isnull=True, customer_visible=True)
        .select_related("service_request", "assigned_business", "category")
        .prefetch_related("messages")
        .order_by("-created_at")[:30]
    )
    read_states = {
        row.ticket_id: row
        for row in TicketConversationReadState.objects.filter(
            user=user,
            scope=TicketConversationReadState.Scope.PERSONAL,
            ticket_id__in=[ticket.id for ticket in tickets],
        )
    }
    rows = []
    for ticket in tickets:
        latest = ticket.messages.order_by("-created_at").first()
        state = read_states.get(ticket.id)
        last_read_id = state.last_read_message_id if state else None
        is_unread = bool(latest and latest.sender_id != user.id and (not last_read_id or latest.id > last_read_id))
        title = (
            ticket.work_title
            or getattr(ticket.service_request, "title", "")
            or getattr(ticket.category, "name", "")
            or f"Request {ticket.ticket_code}"
        )
        rows.append({
            "id": ticket.id,
            "source": "SYNCWORKS",
            "title": title,
            "ticket_code": ticket.ticket_code,
            "status": ticket.customer_status_label or ticket.get_status_display(),
            "provider": ticket.assigned_business.name if ticket.assigned_business else "",
            "latest_message": latest.body[:320] if latest else "",
            "latest_message_at": latest.created_at.isoformat() if latest else ticket.created_at.isoformat(),
            "unread": is_unread,
            "needs_attention": bool(state.needs_attention) if state else False,
            "attention_reason": state.attention_reason if state else "",
            "url": f"/customer/inbox?ticket={ticket.id}",
        })
    return rows


def _external_mail_state(user):
    accounts = []
    messages = []
    for raw in list_connections(user):
        connection = public_connection(raw)
        if not connection.get("mail_enabled"):
            continue
        destinations = {str(v).upper() for v in connection.get("mail_destinations") or []}
        if "PERSONAL" not in destinations:
            continue
        snapshot = connection.get("mail_snapshot") or {}
        accounts.append({
            "id": connection.get("id"),
            "provider": connection.get("provider"),
            "email": connection.get("email"),
            "display_name": connection.get("display_name"),
            "mail_last_synced_at": connection.get("mail_last_synced_at"),
            "mail_last_error": connection.get("mail_last_error") or "",
            "unread_count": int(snapshot.get("unread_count") or 0),
            "high_priority_count": int(snapshot.get("high_priority_count") or 0),
        })
        for item in snapshot.get("messages") or []:
            messages.append({**item, "source": connection.get("provider"), "mailbox": connection.get("email")})
    messages.sort(key=lambda item: str(item.get("received_at") or ""), reverse=True)
    return {
        "available": bool(accounts),
        "accounts": accounts,
        "unread_count": sum(item["unread_count"] for item in accounts),
        "high_priority_count": sum(item["high_priority_count"] for item in accounts),
        "messages": messages[:40],
    }


class SyncAssistantGeocodeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        settings = settings_for(request.user)
        _, profile = load_profile(request.user)
        home = profile.get("home_location") or {}
        address = str(
            request.data.get("address")
            or home.get("label")
            or settings.default_address
            or settings.default_zip
            or ""
        ).strip()
        result = geocode_address(address)
        if not result.get("available"):
            status = 400 if result.get("reason") == "ADDRESS_REQUIRED" else 503 if result.get("reason") == "GEOCODING_NOT_CONFIGURED" else 422
            return Response(result, status=status)
        if bool(request.data.get("save", True)):
            save_profile(request.user, {
                "home_location": {
                    "label": result["label"],
                    "latitude": result["latitude"],
                    "longitude": result["longitude"],
                    "place_id": result.get("place_id") or "",
                }
            })
        return Response(result)


class SyncAssistantInboxStateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        syncworks_rows = _personal_ticket_rows(request.user)
        external = _external_mail_state(request.user)
        unread_syncworks = sum(1 for row in syncworks_rows if row.get("unread"))
        attention_syncworks = sum(1 for row in syncworks_rows if row.get("needs_attention"))
        return Response({
            "syncworks": {
                "available": True,
                "unread_count": unread_syncworks,
                "needs_attention_count": attention_syncworks,
                "conversations": syncworks_rows,
            },
            "external_email": external,
            "total_unread": unread_syncworks + int(external.get("unread_count") or 0),
            "total_high_priority": attention_syncworks + int(external.get("high_priority_count") or 0),
        })
