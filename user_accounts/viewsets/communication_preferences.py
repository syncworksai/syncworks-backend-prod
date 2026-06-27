from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import Business, BusinessMember, CommunicationPreference
from user_accounts.serializers.communication_preferences import CommunicationPreferenceSerializer


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


def _can_access_business(user, business):
    if getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False):
        return True
    if business.owner_id == user.id:
        return True
    return BusinessMember.objects.filter(
        business=business,
        user=user,
        is_active=True,
    ).exists()


class CurrentCommunicationPreferenceAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _resolve_scope(self, request):
        raw = str(
            request.query_params.get("scope")
            or (request.data or {}).get("scope")
            or "PERSONAL"
        ).strip().upper()
        allowed = {choice[0] for choice in CommunicationPreference.Scope.choices}
        if raw not in allowed:
            raise ValidationError({"scope": f"Invalid scope. Allowed: {sorted(allowed)}"})
        return raw

    def _resolve(self, request):
        scope = self._resolve_scope(request)
        business = None

        if scope in {
            CommunicationPreference.Scope.BUSINESS,
            CommunicationPreference.Scope.PROPERTY_MANAGEMENT,
        }:
            business_id = _business_id(request)
            if not business_id:
                raise ValidationError({
                    "business": "An active business is required for this inbox scope."
                })
            business = get_object_or_404(Business, id=business_id, is_active=True)
            if not _can_access_business(request.user, business):
                raise PermissionDenied("You do not have access to this business inbox.")

        preference, _ = CommunicationPreference.objects.get_or_create(
            user=request.user,
            business=business,
            scope=scope,
            defaults={
                "internal_inbox_enabled": True,
                "email_notifications_enabled": True,
                "push_notifications_enabled": True,
                "sms_notifications_enabled": False,
                "automatic_updates_enabled": True,
                "assignment_mode": CommunicationPreference.AssignmentMode.AUTO,
                "owner_oversight_enabled": True,
                "urgent_unread_escalation_enabled": True,
                "email_digest_for_low_priority": True,
                "quiet_hours_enabled": True,
                "timezone": "America/Chicago",
            },
        )
        return preference

    def get(self, request):
        preference = self._resolve(request)
        return Response(CommunicationPreferenceSerializer(preference).data)

    def patch(self, request):
        preference = self._resolve(request)
        serializer = CommunicationPreferenceSerializer(
            preference,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(internal_inbox_enabled=True)
        return Response(serializer.data)
