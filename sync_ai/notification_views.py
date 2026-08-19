from __future__ import annotations

import hashlib
from datetime import datetime

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import CommunicationPreference

from .jarvis_product import load_profile, save_profile
from .notification_engine import notification_settings_payload


def _personal_preference(user):
    preference, _ = CommunicationPreference.objects.get_or_create(
        user=user,
        business=None,
        scope=CommunicationPreference.Scope.PERSONAL,
        defaults={
            "internal_inbox_enabled": True,
            "email_notifications_enabled": True,
            "push_notifications_enabled": True,
            "automatic_updates_enabled": True,
            "urgent_unread_escalation_enabled": True,
            "email_digest_for_low_priority": True,
            "quiet_hours_enabled": True,
            "timezone": "America/Chicago",
        },
    )
    preference.refresh_from_db()
    return preference


def _parse_clock(value, fallback):
    text = str(value or fallback)
    try:
        return datetime.strptime(text, "%H:%M").time()
    except ValueError:
        return datetime.strptime(fallback, "%H:%M").time()


class SyncNotificationSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(notification_settings_payload(request.user))

    def patch(self, request):
        preference = _personal_preference(request.user)
        channels = request.data.get("channels") if isinstance(request.data.get("channels"), dict) else {}
        quiet = request.data.get("quiet_hours") if isinstance(request.data.get("quiet_hours"), dict) else {}
        proactive = request.data.get("proactive") if isinstance(request.data.get("proactive"), dict) else None

        changed = []
        if "email" in channels:
            preference.email_notifications_enabled = bool(channels["email"])
            changed.append("email_notifications_enabled")
        if "push" in channels:
            preference.push_notifications_enabled = bool(channels["push"])
            changed.append("push_notifications_enabled")
        if "email_digest_for_low_priority" in channels:
            preference.email_digest_for_low_priority = bool(channels["email_digest_for_low_priority"])
            changed.append("email_digest_for_low_priority")
        if "enabled" in quiet:
            preference.quiet_hours_enabled = bool(quiet["enabled"])
            changed.append("quiet_hours_enabled")
        if "start" in quiet:
            preference.quiet_hours_start = _parse_clock(quiet["start"], "21:00")
            changed.append("quiet_hours_start")
        if "end" in quiet:
            preference.quiet_hours_end = _parse_clock(quiet["end"], "07:00")
            changed.append("quiet_hours_end")
        if "timezone" in quiet and str(quiet["timezone"] or "").strip():
            preference.timezone = str(quiet["timezone"]).strip()[:64]
            changed.append("timezone")
        if "emergency_override" in quiet:
            preference.emergency_override_enabled = bool(quiet["emergency_override"])
            changed.append("emergency_override_enabled")
        if changed:
            preference.save(update_fields=[*changed, "updated_at"])

        if proactive is not None:
            _, profile = load_profile(request.user)
            modules = profile.get("modules") if isinstance(profile.get("modules"), dict) else {}
            current = modules.get("sync_proactive") if isinstance(modules.get("sync_proactive"), dict) else {}
            save_profile(request.user, {"modules": {"sync_proactive": {**current, **proactive}}})

        return Response(notification_settings_payload(request.user))


class SyncPushDeviceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = str(request.data.get("token") or "").strip()
        if not token:
            return Response({"detail": "A push token is required."}, status=400)
        platform = str(request.data.get("platform") or "unknown").strip().lower()[:32]
        provider = str(request.data.get("provider") or "future").strip().lower()[:32]
        label = str(request.data.get("label") or "Device").strip()[:80]
        token_id = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
        now = timezone.now().isoformat()

        _, profile = load_profile(request.user)
        modules = profile.get("modules") if isinstance(profile.get("modules"), dict) else {}
        devices = modules.get("push_devices") if isinstance(modules.get("push_devices"), list) else []
        next_devices = []
        found = False
        for row in devices:
            if not isinstance(row, dict):
                continue
            if row.get("id") == token_id or row.get("token") == token:
                next_devices.append({**row, "id": token_id, "token": token, "platform": platform, "provider": provider, "label": label, "active": True, "last_seen_at": now})
                found = True
            else:
                next_devices.append(row)
        if not found:
            next_devices.append({"id": token_id, "token": token, "platform": platform, "provider": provider, "label": label, "active": True, "registered_at": now, "last_seen_at": now})
        save_profile(request.user, {"modules": {"push_devices": next_devices[-10:]}})
        return Response(notification_settings_payload(request.user), status=201 if not found else 200)

    def delete(self, request):
        token_id = str(request.data.get("id") or "").strip()
        token = str(request.data.get("token") or "").strip()
        if not token_id and not token:
            return Response({"detail": "A device id or token is required."}, status=400)
        _, profile = load_profile(request.user)
        modules = profile.get("modules") if isinstance(profile.get("modules"), dict) else {}
        devices = modules.get("push_devices") if isinstance(modules.get("push_devices"), list) else []
        next_devices = [row for row in devices if isinstance(row, dict) and row.get("id") != token_id and row.get("token") != token]
        save_profile(request.user, {"modules": {"push_devices": next_devices}})
        return Response(notification_settings_payload(request.user))
