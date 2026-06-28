from __future__ import annotations

from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import (
    CommunicationPreference,
    OperationalAlert,
    OperationalEvent,
    TicketETA,
)
from user_accounts.serializers.operations import (
    OperationalAlertSerializer,
    OperationalEventSerializer,
    TicketETASerializer,
)
from user_accounts.viewsets.ticket_conversations import (
    _business_context,
    _visible_tickets,
)


def _ticket_or_404(request, ticket_id):
    ticket = _visible_tickets(request, "BUSINESS").filter(id=ticket_id).first()
    if not ticket:
        raise Http404
    return ticket


def _channel_allowed(user, business, channel):
    preference = CommunicationPreference.objects.filter(
        user=user,
        business=business,
        scope=CommunicationPreference.Scope.BUSINESS,
    ).first()
    if not preference:
        return channel == OperationalAlert.Channel.IN_APP
    mapping = {
        OperationalAlert.Channel.IN_APP: preference.internal_inbox_enabled,
        OperationalAlert.Channel.EMAIL: preference.email_notifications_enabled,
        OperationalAlert.Channel.PUSH: preference.push_notifications_enabled,
        OperationalAlert.Channel.SMS: preference.sms_ready,
    }
    return bool(mapping.get(channel, False))


def _alert_recipient(ticket, audience, recipient):
    if audience == OperationalAlert.Audience.CUSTOMER:
        return ticket.customer
    if audience == OperationalAlert.Audience.BUSINESS:
        return ticket.assigned_member or (
            ticket.assigned_business.owner if ticket.assigned_business else None
        )
    return recipient


def create_alert_for_event(
    *,
    event,
    audience,
    channel,
    recipient=None,
    dedupe_suffix="",
):
    resolved = _alert_recipient(event.ticket, audience, recipient)
    if not resolved:
        raise ValidationError({"recipient": "No recipient could be resolved."})

    dedupe_key = (
        f"event:{event.id}:{audience}:{channel}:{dedupe_suffix or 'default'}"
    )
    allowed = _channel_allowed(resolved, event.business, channel)
    defaults = {
        "event": event,
        "audience": audience,
        "status": (
            OperationalAlert.Status.PENDING
            if allowed
            else OperationalAlert.Status.SUPPRESSED
        ),
    }
    try:
        alert, created = OperationalAlert.objects.get_or_create(
            recipient=resolved,
            channel=channel,
            dedupe_key=dedupe_key,
            defaults=defaults,
        )
    except IntegrityError:
        alert = OperationalAlert.objects.get(
            recipient=resolved,
            channel=channel,
            dedupe_key=dedupe_key,
        )
        created = False
    return alert, created


class TicketETAAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, ticket_id):
        ticket = _ticket_or_404(request, ticket_id)
        eta = TicketETA.objects.filter(ticket=ticket).first()
        if not eta:
            return Response({"ticket_id": ticket.id, "eta": None})
        return Response(TicketETASerializer(eta).data)

    def put(self, request, ticket_id):
        business, _, _ = _business_context(request)
        ticket = _ticket_or_404(request, ticket_id)
        eta = TicketETA.objects.filter(ticket=ticket).first()
        serializer = TicketETASerializer(
            eta,
            data=request.data,
            partial=False,
        )
        serializer.is_valid(raise_exception=True)

        previous_status = eta.status if eta else None
        with transaction.atomic():
            eta = serializer.save(ticket=ticket, updated_by=request.user)
            event_type = (
                OperationalEvent.EventType.DELAY_REPORTED
                if eta.status == TicketETA.Status.DELAYED
                else OperationalEvent.EventType.ETA_UPDATED
            )
            event = OperationalEvent.objects.create(
                business=business,
                ticket=ticket,
                event_type=event_type,
                visibility=OperationalEvent.Visibility.BOTH,
                title=(
                    "Arrival delayed"
                    if eta.status == TicketETA.Status.DELAYED
                    else "Arrival estimate updated"
                ),
                message=eta.customer_message or eta.delay_reason,
                data={
                    "eta_id": eta.id,
                    "previous_status": previous_status,
                    "status": eta.status,
                    "estimated_arrival": (
                        eta.estimated_arrival.isoformat()
                        if eta.estimated_arrival
                        else None
                    ),
                },
                created_by=request.user,
            )
            create_alert_for_event(
                event=event,
                audience=OperationalAlert.Audience.CUSTOMER,
                channel=OperationalAlert.Channel.IN_APP,
                dedupe_suffix=str(eta.updated_at.timestamp()),
            )

        return Response(TicketETASerializer(eta).data)


class TicketEventListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, ticket_id):
        ticket = _ticket_or_404(request, ticket_id)
        events = ticket.operational_events.select_related("created_by")
        return Response({
            "ticket_id": ticket.id,
            "results": OperationalEventSerializer(events, many=True).data,
        })

    def post(self, request, ticket_id):
        business, _, _ = _business_context(request)
        ticket = _ticket_or_404(request, ticket_id)
        serializer = OperationalEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = serializer.save(
            business=business,
            ticket=ticket,
            created_by=request.user,
        )
        return Response(OperationalEventSerializer(event).data, status=201)


class EventAlertCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, event_id):
        business, _, _ = _business_context(request)
        event = OperationalEvent.objects.select_related(
            "ticket__customer",
            "ticket__assigned_member",
            "ticket__assigned_business__owner",
        ).filter(id=event_id, business=business).first()
        if not event:
            raise Http404

        audience = str(request.data.get("audience") or "").upper()
        channel = str(request.data.get("channel") or "").upper()
        recipient = None
        if audience == OperationalAlert.Audience.USER:
            recipient_id = request.data.get("recipient")
            if recipient_id:
                from django.contrib.auth import get_user_model
                recipient = get_user_model().objects.filter(id=recipient_id).first()

        valid_audiences = {choice[0] for choice in OperationalAlert.Audience.choices}
        valid_channels = {choice[0] for choice in OperationalAlert.Channel.choices}
        if audience not in valid_audiences:
            raise ValidationError({"audience": "Invalid alert audience."})
        if channel not in valid_channels:
            raise ValidationError({"channel": "Invalid alert channel."})

        alert, created = create_alert_for_event(
            event=event,
            audience=audience,
            channel=channel,
            recipient=recipient,
            dedupe_suffix=str(request.data.get("dedupe_suffix") or ""),
        )
        return Response(
            {
                "created": created,
                "alert": OperationalAlertSerializer(alert).data,
            },
            status=201 if created else 200,
        )


class OperationalAlertListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = OperationalAlert.objects.filter(
            recipient=request.user,
        ).select_related("event", "event__ticket")
        unread_only = str(
            request.query_params.get("unread_only") or ""
        ).lower() in {"1", "true", "yes"}
        if unread_only:
            rows = rows.filter(read_at__isnull=True)
        return Response(OperationalAlertSerializer(rows[:200], many=True).data)


class OperationalAlertDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, alert_id):
        alert = OperationalAlert.objects.filter(
            id=alert_id,
            recipient=request.user,
        ).first()
        if not alert:
            raise Http404

        action = str(request.data.get("action") or "").lower()
        update_fields = []
        if action == "read":
            if not alert.read_at:
                alert.read_at = timezone.now()
                update_fields.append("read_at")
        elif action == "acknowledge":
            now = timezone.now()
            if not alert.read_at:
                alert.read_at = now
                update_fields.append("read_at")
            alert.acknowledged_at = now
            alert.status = OperationalAlert.Status.ACKNOWLEDGED
            update_fields.extend(["acknowledged_at", "status"])
        elif action == "sent":
            alert.status = OperationalAlert.Status.SENT
            alert.delivered_at = timezone.now()
            update_fields.extend(["status", "delivered_at"])
        else:
            raise ValidationError(
                {"action": "Use read, acknowledge, or sent."}
            )

        if update_fields:
            alert.save(update_fields=list(dict.fromkeys(update_fields)))
        return Response(OperationalAlertSerializer(alert).data)
