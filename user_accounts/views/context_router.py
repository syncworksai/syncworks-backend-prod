from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import PersonalIdentity, UserLocation

CURRENT_FEATURES = {"WEATHER", "TRAFFIC", "NEARBY", "LOCAL_INFO", "FOOD", "RETAIL"}
HOME_FEATURES = {"SERVICE", "SHIPPING", "HOME", "HOUSEHOLD"}


def _location_payload(location: UserLocation | None):
    if not location:
        return None
    return {
        "id": location.id,
        "kind": location.kind,
        "label": location.label,
        "address_line1": location.address_line1,
        "address_line2": location.address_line2,
        "city": location.city,
        "state": location.state,
        "postal_code": location.postal_code,
        "country": location.country,
        "latitude": float(location.latitude) if location.latitude is not None else None,
        "longitude": float(location.longitude) if location.longitude is not None else None,
        "formatted_address": location.formatted_address,
        "is_default_service": location.is_default_service,
    }


class ContextLocationRouterAPIView(APIView):
    """Resolve which location source a feature should use.

    Device coordinates are request-scoped only. They are never persisted and
    never overwrite Home.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        feature = str(request.data.get("feature") or "").strip().upper()
        if not feature:
            return Response({"detail": "feature is required."}, status=status.HTTP_400_BAD_REQUEST)

        identity, _ = PersonalIdentity.objects.get_or_create(user=request.user)
        home = UserLocation.objects.filter(user=request.user, kind=UserLocation.Kind.HOME).first()
        default_service = UserLocation.objects.filter(user=request.user, is_default_service=True).first() or home

        current_allowed = {
            "WEATHER": identity.use_current_for_weather,
            "TRAFFIC": identity.use_current_for_traffic,
            "NEARBY": identity.use_current_for_nearby,
            "FOOD": identity.use_current_for_nearby,
            "RETAIL": identity.use_current_for_nearby,
            "LOCAL_INFO": identity.use_current_for_local_info,
        }.get(feature, False)

        current = None
        lat = request.data.get("latitude")
        lng = request.data.get("longitude")
        if lat not in (None, "") and lng not in (None, ""):
            try:
                latitude = float(lat)
                longitude = float(lng)
                if -90 <= latitude <= 90 and -180 <= longitude <= 180:
                    current = {
                        "latitude": latitude,
                        "longitude": longitude,
                        "label": str(request.data.get("current_label") or "Current location").strip(),
                        "persisted": False,
                    }
            except (TypeError, ValueError):
                current = None

        if feature in CURRENT_FEATURES and current_allowed and current:
            source = "CURRENT"
            resolved = current
            fallback_used = False
        elif feature in HOME_FEATURES:
            source = "HOME"
            resolved = _location_payload(default_service)
            fallback_used = False
        elif feature in CURRENT_FEATURES:
            source = "HOME_FALLBACK"
            resolved = _location_payload(home)
            fallback_used = True
        else:
            source = "HOME"
            resolved = _location_payload(default_service)
            fallback_used = False

        return Response({
            "feature": feature,
            "source": source,
            "location": resolved,
            "fallback_used": fallback_used,
            "current_location_persisted": False,
            "home_overwritten": False,
            "preference": {"current_allowed": bool(current_allowed)},
            "rule": "Current location is preferred for local context; Home/default service location is preferred for service, shipping and household context.",
        })
