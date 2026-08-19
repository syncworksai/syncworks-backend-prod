from __future__ import annotations

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from personal_calendar.models import PersonalCalendarEvent, PersonalCalendarEventAudit
from user_accounts.models import AuditLog

from .assistant_daily_state import build_daily_state
from .jarvis_product import load_profile, save_profile, settings_for
from .location_intelligence import geocode_address


def _ensure_home_coordinates(user):
    settings = settings_for(user)
    _, profile = load_profile(user)
    home = profile.get("home_location") or {}
    if home.get("latitude") is not None and home.get("longitude") is not None:
        return
    address = str(home.get("label") or settings.default_address or settings.default_zip or "").strip()
    if not address:
        return
    result = geocode_address(address)
    if not result.get("available"):
        return
    save_profile(user, {
        "home_location": {
            "label": result["label"],
            "latitude": result["latitude"],
            "longitude": result["longitude"],
            "place_id": result.get("place_id") or "",
        }
    })


class SyncAssistantDailyStateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        _ensure_home_coordinates(request.user)
        payload = build_daily_state(request.user)
        AuditLog.objects.create(
            actor=request.user,
            action="sync_assistant.daily_state.viewed",
            metadata={
                "local_date": payload.get("local_date"),
                "needs_attention": len(payload.get("needs_attention") or []),
            },
        )
        return Response(payload)


class SyncAssistantDepartureReminderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, event_id):
        event = PersonalCalendarEvent.objects.filter(owner=request.user, id=event_id, status="ACTIVE").first()
        if event is None:
            return Response({"detail": "Calendar event not found."}, status=404)
        try:
            arrival_buffer = int(request.data.get("arrival_buffer_minutes", event.arrival_buffer_minutes or 0))
            reminder_minutes = int(request.data.get("reminder_minutes", event.reminder_minutes or 30))
        except (TypeError, ValueError):
            return Response({"detail": "Reminder values must be whole minutes."}, status=400)
        if not 0 <= arrival_buffer <= 240:
            return Response({"detail": "Arrival buffer must be between 0 and 240 minutes."}, status=400)
        if not 0 <= reminder_minutes <= 10080:
            return Response({"detail": "Reminder must be between 0 and 10080 minutes."}, status=400)
        old = {
            "arrival_buffer_minutes": event.arrival_buffer_minutes,
            "reminder_minutes": event.reminder_minutes,
        }
        metadata = dict(event.metadata or {})
        metadata["sync_departure_reminder_enabled"] = bool(request.data.get("enabled", True))
        metadata["sync_departure_reminder_updated_at"] = timezone.now().isoformat()
        metadata.pop("sync_departure_reminder_sent_at", None)
        event.arrival_buffer_minutes = arrival_buffer
        event.reminder_minutes = reminder_minutes
        event.metadata = metadata
        event.save(update_fields=["arrival_buffer_minutes", "reminder_minutes", "metadata", "updated_at"])
        PersonalCalendarEventAudit.objects.create(
            event=event,
            actor=request.user,
            action=PersonalCalendarEventAudit.Action.UPDATED,
            changes={
                "arrival_buffer_minutes": [old["arrival_buffer_minutes"], arrival_buffer],
                "reminder_minutes": [old["reminder_minutes"], reminder_minutes],
                "sync_departure_reminder_enabled": metadata["sync_departure_reminder_enabled"],
            },
        )
        return Response({
            "event_id": event.id,
            "enabled": metadata["sync_departure_reminder_enabled"],
            "arrival_buffer_minutes": event.arrival_buffer_minutes,
            "reminder_minutes": event.reminder_minutes,
        })
