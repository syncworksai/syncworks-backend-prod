# backend/user_accounts/viewsets/sales_calendar.py
from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from user_accounts.models.sales_calendar import SalesCalendarEvent
from user_accounts.models.sales_os import SalesPipeline, SalesPipelineMember, SalesMemberEmailSettings
from user_accounts.serializers.sales_calendar import SalesCalendarEventSerializer, SalesCalendarRangeQuerySerializer


def _require_member(pipeline: SalesPipeline, user) -> SalesPipelineMember:
    m = SalesPipelineMember.objects.filter(pipeline=pipeline, user=user).first()
    if not m:
        raise permissions.PermissionDenied("Not a member of this sales pipeline.")
    return m


def _is_manager(member: SalesPipelineMember) -> bool:
    return member.role in (SalesPipelineMember.ROLE_OWNER, SalesPipelineMember.ROLE_MANAGER)


def _deny_if_locked(pipeline: SalesPipeline):
    if pipeline.is_locked or (not pipeline.is_active):
        raise permissions.PermissionDenied("Sales Pipeline is locked (billing). Read-only mode.")


def _dt_to_ics(dt):
    # UTC format for ICS
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ics_escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def _member_calendar_email(member: SalesPipelineMember) -> str:
    # Matches “email on file in settings”
    settings_obj = getattr(member, "email_settings", None)
    if settings_obj and settings_obj.is_enabled and settings_obj.from_email:
        return settings_obj.from_email
    return getattr(member.user, "email", "") or ""


def _event_to_ics(event: SalesCalendarEvent, organizer_email: str) -> str:
    uid = f"syncworks-sales-{event.id}@syncworks"
    dtstamp = _dt_to_ics(timezone.now())
    dtstart = _dt_to_ics(event.start_at)
    dtend = _dt_to_ics(event.end_at)

    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{dtstart}",
        f"DTEND:{dtend}",
        f"SUMMARY:{_ics_escape(event.title)}",
    ]

    if event.description:
        lines.append(f"DESCRIPTION:{_ics_escape(event.description)}")
    if event.location:
        lines.append(f"LOCATION:{_ics_escape(event.location)}")
    if organizer_email:
        lines.append(f"ORGANIZER:MAILTO:{_ics_escape(organizer_email)}")

    lines.append("END:VEVENT")
    return "\r\n".join(lines)


class SalesCalendarEventViewSet(viewsets.ModelViewSet):
    serializer_class = SalesCalendarEventSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Only events in pipelines the user belongs to
        qs = SalesCalendarEvent.objects.filter(pipeline__members__user=self.request.user).distinct()

        pipeline_id = self.request.query_params.get("pipeline_id")
        if pipeline_id:
            qs = qs.filter(pipeline_id=pipeline_id)

        # Optional date-range filters
        start = self.request.query_params.get("start")
        end = self.request.query_params.get("end")
        if start:
            qs = qs.filter(end_at__gte=start)
        if end:
            qs = qs.filter(start_at__lte=end)

        # If pipeline provided and user is an AGENT, show only assigned to them + created by them
        if pipeline_id:
            pipeline = get_object_or_404(SalesPipeline, pk=pipeline_id)
            member = _require_member(pipeline, self.request.user)
            if not _is_manager(member):
                qs = qs.filter(assigned_member=member) | qs.filter(created_by=self.request.user)

        return qs.select_related("pipeline", "assigned_member", "assigned_member__user", "prospect")

    def perform_create(self, serializer):
        pipeline_id = serializer.validated_data["pipeline_id"]
        pipeline = get_object_or_404(SalesPipeline, pk=pipeline_id)
        member = _require_member(pipeline, self.request.user)
        _deny_if_locked(pipeline)

        # Default assign to creator if not set
        assigned_member_id = serializer.validated_data.get("assigned_member_id")
        if not assigned_member_id:
            serializer.save(pipeline=pipeline, created_by=self.request.user, assigned_member=member)
            return

        # Ensure assigned member in same pipeline
        assigned_member = get_object_or_404(SalesPipelineMember, pk=assigned_member_id, pipeline=pipeline)
        serializer.save(pipeline=pipeline, created_by=self.request.user, assigned_member=assigned_member)

    def update(self, request, *args, **kwargs):
        obj = self.get_object()
        member = _require_member(obj.pipeline, request.user)
        _deny_if_locked(obj.pipeline)

        # Agent can update only if assigned/created
        if not _is_manager(member) and not (obj.assigned_member_id == member.id or obj.created_by_id == request.user.id):
            raise permissions.PermissionDenied("Agents can only modify their events.")

        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        member = _require_member(obj.pipeline, request.user)
        _deny_if_locked(obj.pipeline)

        if not _is_manager(member) and not (obj.assigned_member_id == member.id or obj.created_by_id == request.user.id):
            raise permissions.PermissionDenied("Agents can only delete their events.")

        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["get"], url_path="ics")
    def ics(self, request, pk=None):
        event = self.get_object()
        member = _require_member(event.pipeline, request.user)

        organizer_email = _member_calendar_email(member)
        ics = "\r\n".join([
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//SyncWorks//SalesOS//EN",
            _event_to_ics(event, organizer_email),
            "END:VCALENDAR",
            "",
        ])

        resp = HttpResponse(ics, content_type="text/calendar; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="sales-event-{event.id}.ics"'
        return resp

    @action(detail=False, methods=["get"], url_path="week")
    def week(self, request):
        """
        Quick-glance range helper:
        /sales/events/week/?pipeline_id=123
        Returns events from now -> next 7 days.
        """
        q = SalesCalendarRangeQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)

        pipeline = get_object_or_404(SalesPipeline, pk=q.validated_data["pipeline_id"])
        member = _require_member(pipeline, request.user)

        start = timezone.now()
        end = start + timedelta(days=7)

        qs = SalesCalendarEvent.objects.filter(pipeline=pipeline, start_at__lte=end, end_at__gte=start)

        if not _is_manager(member):
            qs = qs.filter(assigned_member=member) | qs.filter(created_by=request.user)

        qs = qs.order_by("start_at")
        return Response(SalesCalendarEventSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="add-links")
    def add_links(self, request):
        """
        Returns URL templates for Add to Google / Outlook web
        (Apple uses ICS download).
        Frontend can build links per-event, but this endpoint can be used later for consistency.
        """
        return Response({
            "google_hint": "Use https://calendar.google.com/calendar/render?action=TEMPLATE&text=TITLE&dates=START/END&details=DESC&location=LOC",
            "outlook_hint": "Use https://outlook.live.com/calendar/0/deeplink/compose?subject=TITLE&startdt=ISO&enddt=ISO&body=DESC&location=LOC",
            "apple_hint": "Use /sales/events/<id>/ics to download ICS",
        })