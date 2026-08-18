from django.db import transaction
from django.utils.dateparse import parse_datetime
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

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
