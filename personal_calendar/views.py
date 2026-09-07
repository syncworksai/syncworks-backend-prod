from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models.tickets import Ticket, TicketMessage

from .models import PersonalCalendarEvent, PersonalCalendarEventAudit
from .serializers import PersonalCalendarEventSerializer
from .travel_assist import TravelAssistError, build_travel_plan
from .travel_monitor import disable_trip_monitoring, enable_trip_monitoring, refresh_monitored_trip


class PersonalCalendarEventViewSet(viewsets.ModelViewSet):
    serializer_class = PersonalCalendarEventSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = (
            PersonalCalendarEvent.objects.filter(owner=self.request.user)
            .prefetch_related("audit_entries")
            .order_by("start_at", "id")
        )
        requested_status = self.request.query_params.get("status")
        if requested_status:
            queryset = queryset.filter(status=requested_status.upper())
        start_value = self.request.query_params.get("start")
        if start_value:
            parsed = parse_datetime(start_value)
            if parsed:
                queryset = queryset.filter(start_at__gte=parsed)
        end_value = self.request.query_params.get("end")
        if end_value:
            parsed = parse_datetime(end_value)
            if parsed:
                queryset = queryset.filter(start_at__lte=parsed)
        source = self.request.query_params.get("source")
        if source:
            queryset = queryset.filter(source=source.upper())
        return queryset

    def perform_create(self, serializer):
        with transaction.atomic():
            event = serializer.save(owner=self.request.user)
            PersonalCalendarEventAudit.objects.create(
                event=event,
                actor=self.request.user,
                action=PersonalCalendarEventAudit.Action.CREATED,
                changes={"source": event.source},
            )

    def perform_update(self, serializer):
        changed_fields = sorted(serializer.validated_data.keys())
        with transaction.atomic():
            event = serializer.save()
            PersonalCalendarEventAudit.objects.create(
                event=event,
                actor=self.request.user,
                action=PersonalCalendarEventAudit.Action.UPDATED,
                changes={"fields": changed_fields},
            )

    def perform_destroy(self, instance):
        with transaction.atomic():
            instance.status = PersonalCalendarEvent.Status.ARCHIVED
            instance.save(update_fields=("status", "updated_at"))
            PersonalCalendarEventAudit.objects.create(
                event=instance,
                actor=self.request.user,
                action=PersonalCalendarEventAudit.Action.DELETED,
                changes={"soft_delete": True},
            )

    def _change_status(self, request, event_status, audit_action):
        event = self.get_object()
        with transaction.atomic():
            event.status = event_status
            event.save(update_fields=("status", "updated_at"))
            PersonalCalendarEventAudit.objects.create(
                event=event,
                actor=request.user,
                action=audit_action,
                changes={"status": event_status},
            )
        return Response(self.get_serializer(event).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        return self._change_status(
            request,
            PersonalCalendarEvent.Status.ARCHIVED,
            PersonalCalendarEventAudit.Action.ARCHIVED,
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._change_status(
            request,
            PersonalCalendarEvent.Status.CANCELLED,
            PersonalCalendarEventAudit.Action.CANCELLED,
        )

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        event = self.get_object()
        with transaction.atomic():
            event.status = PersonalCalendarEvent.Status.ACTIVE
            event.save(update_fields=("status", "updated_at"))
            PersonalCalendarEventAudit.objects.create(
                event=event,
                actor=request.user,
                action=PersonalCalendarEventAudit.Action.UPDATED,
                changes={"status": PersonalCalendarEvent.Status.ACTIVE},
            )
        return Response(self.get_serializer(event).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="schedule-response")
    def schedule_response(self, request, pk=None):
        event = self.get_object()
        if event.source != PersonalCalendarEvent.Source.TICKET:
            raise serializers.ValidationError("Schedule responses are only available for SyncWorks service appointments.")

        response_value = str(request.data.get("response") or "").strip().upper()
        response_map = {
            "ACCEPT": "ACCEPTED",
            "ACCEPTED": "ACCEPTED",
            "REQUEST_CHANGE": "REQUESTED_DIFFERENT_TIME",
            "REQUESTED_DIFFERENT_TIME": "REQUESTED_DIFFERENT_TIME",
            "DECLINE": "REQUESTED_DIFFERENT_TIME",
            "DECLINED": "REQUESTED_DIFFERENT_TIME",
        }
        response_status = response_map.get(response_value)
        if not response_status:
            raise serializers.ValidationError({"response": "Use ACCEPT or REQUEST_CHANGE."})

        metadata = dict(event.metadata or {})
        schedule_change = metadata.get("schedule_change") if isinstance(metadata.get("schedule_change"), dict) else {}
        if (
            not schedule_change
            or not bool(schedule_change.get("requires_response"))
            or str(schedule_change.get("status") or "").upper() != "PENDING"
        ):
            raise serializers.ValidationError("There is no service schedule change waiting for a response.")

        responded_at = timezone.now().isoformat()
        response_note = str(request.data.get("note") or "").strip()[:500]
        schedule_change = {
            **schedule_change,
            "status": response_status,
            "requires_response": False,
            "responded_at": responded_at,
            "response_note": response_note,
        }
        metadata["schedule_change"] = schedule_change
        history = list(metadata.get("schedule_history") or [])
        if history:
            history[-1] = {
                **history[-1],
                "status": response_status,
                "responded_at": responded_at,
                "response_note": response_note,
            }
            metadata["schedule_history"] = history[-20:]

        ticket_id = metadata.get("ticket_id")
        ticket = Ticket.objects.filter(pk=ticket_id, customer=request.user).first() if ticket_id else None
        proposed_start = str(schedule_change.get("proposed_start") or "").strip()
        if response_status == "ACCEPTED":
            ticket_message = f"Customer accepted the service schedule{f' for {proposed_start}' if proposed_start else ''} from SyncWorks Calendar."
        else:
            ticket_message = f"Customer requested a different service time{f' from the proposed {proposed_start}' if proposed_start else ''} in SyncWorks Calendar."
            if response_note:
                ticket_message = f"{ticket_message} Note: {response_note}"

        with transaction.atomic():
            event.metadata = metadata
            event.save(update_fields=("metadata", "updated_at"))
            if ticket is not None:
                TicketMessage.objects.create(
                    ticket=ticket,
                    sender=request.user,
                    type=TicketMessage.MessageType.SYSTEM,
                    body=ticket_message,
                )
            PersonalCalendarEventAudit.objects.create(
                event=event,
                actor=request.user,
                action=PersonalCalendarEventAudit.Action.UPDATED,
                changes={
                    "fields": ["metadata.schedule_change"],
                    "schedule_response": response_status,
                    "ticket_message_created": bool(ticket),
                },
            )
        return Response(self.get_serializer(event).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="travel-plan")
    def travel_plan(self, request, pk=None):
        event = self.get_object()
        latitude = request.data.get("latitude")
        longitude = request.data.get("longitude")
        try:
            plan = build_travel_plan(event, latitude, longitude)
        except TravelAssistError as exc:
            raise serializers.ValidationError(str(exc)) from exc

        metadata = dict(event.metadata or {})
        metadata["travel_assist"] = plan
        with transaction.atomic():
            event.metadata = metadata
            event.save(update_fields=("metadata", "updated_at"))
            PersonalCalendarEventAudit.objects.create(
                event=event,
                actor=request.user,
                action=PersonalCalendarEventAudit.Action.UPDATED,
                changes={
                    "fields": ["metadata.travel_assist"],
                    "travel_provider": plan.get("route", {}).get("provider"),
                    "weather_provider": plan.get("weather", {}).get("provider"),
                },
            )
        return Response(plan, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="travel-monitor")
    def travel_monitor(self, request, pk=None):
        event = self.get_object()
        enabled = bool(request.data.get("enabled", True))
        try:
            if enabled:
                monitor = enable_trip_monitoring(
                    event,
                    request.data.get("latitude"),
                    request.data.get("longitude"),
                )
                result = refresh_monitored_trip(event)
            else:
                monitor = disable_trip_monitoring(event)
                result = {"status": "DISABLED"}
        except TravelAssistError as exc:
            raise serializers.ValidationError(str(exc)) from exc

        PersonalCalendarEventAudit.objects.create(
            event=event,
            actor=request.user,
            action=PersonalCalendarEventAudit.Action.UPDATED,
            changes={
                "fields": ["metadata.travel_monitor"],
                "travel_monitor_enabled": enabled,
            },
        )
        event.refresh_from_db(fields=("metadata", "updated_at"))
        return Response(
            {
                "monitor": (event.metadata or {}).get("travel_monitor") or monitor,
                "travel_assist": (event.metadata or {}).get("travel_assist"),
                "result": result,
            },
            status=status.HTTP_200_OK,
        )
