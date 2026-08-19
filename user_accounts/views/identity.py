from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import (
    Business,
    BusinessMember,
    BusinessVerification,
    CustomerSettings,
    PersonalIdentity,
    UserLocation,
)


IDENTITY_FIELDS = {
    "display_name",
    "phone",
    "bio",
    "public_city",
    "public_state",
    "show_photo_services",
    "show_photo_social",
    "show_photo_groups",
    "show_city_public",
    "use_current_for_weather",
    "use_current_for_traffic",
    "use_current_for_nearby",
    "use_current_for_local_info",
    "onboarding_completed",
}

LOCATION_FIELDS = {
    "kind",
    "label",
    "address_line1",
    "address_line2",
    "city",
    "state",
    "postal_code",
    "country",
    "latitude",
    "longitude",
    "is_default_service",
}


def _identity(user) -> PersonalIdentity:
    identity, created = PersonalIdentity.objects.get_or_create(
        user=user,
        defaults={
            "display_name": " ".join(part for part in [user.first_name, user.last_name] if part).strip(),
        },
    )
    if created:
        try:
            legacy = CustomerSettings.objects.filter(user=user).first()
            if legacy:
                identity.phone = legacy.phone or ""
                if legacy.profile_photo:
                    identity.profile_photo = legacy.profile_photo
                identity.save()
        except Exception:
            pass
    return identity


def _photo_url(request, identity: PersonalIdentity):
    if not identity.profile_photo:
        return None
    try:
        return request.build_absolute_uri(identity.profile_photo.url)
    except Exception:
        return None


def _location_payload(location: UserLocation) -> dict:
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
        "is_default_service": location.is_default_service,
        "formatted_address": location.formatted_address,
        "updated_at": location.updated_at.isoformat() if location.updated_at else None,
    }


def _profile_payload(request, user, identity: PersonalIdentity) -> dict:
    locations = list(UserLocation.objects.filter(user=user))
    home = next((item for item in locations if item.kind == UserLocation.Kind.HOME), None)
    default_service = next((item for item in locations if item.is_default_service), None) or home
    basics_complete = bool(user.first_name and user.last_name and identity.phone and home)
    return {
        "user": {
            "id": user.id,
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "email": user.email or "",
            "email_verified": bool(getattr(user, "email_verified", False)),
        },
        "identity": {
            "display_name": identity.display_name,
            "phone": identity.phone,
            "bio": identity.bio,
            "public_city": identity.public_city,
            "public_state": identity.public_state,
            "profile_photo_url": _photo_url(request, identity),
            "show_photo_services": identity.show_photo_services,
            "show_photo_social": identity.show_photo_social,
            "show_photo_groups": identity.show_photo_groups,
            "show_city_public": identity.show_city_public,
            "use_current_for_weather": identity.use_current_for_weather,
            "use_current_for_traffic": identity.use_current_for_traffic,
            "use_current_for_nearby": identity.use_current_for_nearby,
            "use_current_for_local_info": identity.use_current_for_local_info,
            "onboarding_completed": identity.onboarding_completed,
        },
        "home_location": _location_payload(home) if home else None,
        "default_service_location": _location_payload(default_service) if default_service else None,
        "locations": [_location_payload(item) for item in locations],
        "onboarding": {
            "complete": bool(identity.onboarding_completed),
            "basics_complete": basics_complete,
            "missing": [
                label
                for label, present in (
                    ("first_name", bool(user.first_name)),
                    ("last_name", bool(user.last_name)),
                    ("phone", bool(identity.phone)),
                    ("home_location", bool(home)),
                )
                if not present
            ],
        },
        "privacy": {
            "home_location_public": False,
            "current_location_public": False,
            "note": "Home and current device location are operational data and are never public profile fields.",
        },
    }


def _set_location_values(location: UserLocation, data) -> None:
    for field in LOCATION_FIELDS:
        if field not in data:
            continue
        value = data.get(field)
        if field in {"latitude", "longitude"}:
            if value in (None, ""):
                value = None
            else:
                try:
                    value = Decimal(str(value))
                except (InvalidOperation, TypeError, ValueError):
                    value = None
        elif field == "is_default_service":
            value = bool(value)
        elif field == "kind":
            value = str(value or UserLocation.Kind.SAVED).upper()
            allowed = {choice[0] for choice in UserLocation.Kind.choices}
            if value not in allowed:
                value = UserLocation.Kind.SAVED
        else:
            value = str(value or "").strip()
        setattr(location, field, value)


def _normalize_location_uniqueness(location: UserLocation) -> None:
    if location.kind == UserLocation.Kind.HOME:
        UserLocation.objects.filter(user=location.user, kind=UserLocation.Kind.HOME).exclude(pk=location.pk).update(kind=UserLocation.Kind.SAVED)
        location.is_default_service = True
    if location.is_default_service:
        UserLocation.objects.filter(user=location.user, is_default_service=True).exclude(pk=location.pk).update(is_default_service=False)


class IdentityProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request):
        return Response(_profile_payload(request, request.user, _identity(request.user)))

    @transaction.atomic
    def patch(self, request):
        user = request.user
        identity = _identity(user)

        for field in ("first_name", "last_name"):
            if field in request.data:
                setattr(user, field, str(request.data.get(field) or "").strip()[:150])
        user.save(update_fields=["first_name", "last_name"])

        for field in IDENTITY_FIELDS:
            if field not in request.data:
                continue
            value = request.data.get(field)
            if field.startswith("show_") or field.startswith("use_current_") or field == "onboarding_completed":
                if isinstance(value, str):
                    value = value.strip().lower() in {"1", "true", "yes", "on"}
                else:
                    value = bool(value)
            else:
                value = str(value or "").strip()
            setattr(identity, field, value)

        uploaded = request.FILES.get("profile_photo")
        if uploaded:
            identity.profile_photo = uploaded
        identity.save()

        # Keep the legacy CustomerSettings phone/profile photo synchronized while
        # older request and account screens transition to the canonical identity.
        legacy, _ = CustomerSettings.objects.get_or_create(user=user)
        legacy.phone = identity.phone
        if identity.profile_photo:
            legacy.profile_photo = identity.profile_photo
        legacy.save(update_fields=["phone", "profile_photo", "updated_at"])

        return Response(_profile_payload(request, user, identity))


class IdentityLocationsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = UserLocation.objects.filter(user=request.user)
        return Response([_location_payload(row) for row in rows])

    @transaction.atomic
    def post(self, request):
        address = str(request.data.get("address_line1") or "").strip()
        if not address:
            return Response({"address_line1": "Street address is required."}, status=status.HTTP_400_BAD_REQUEST)
        location = UserLocation(user=request.user, address_line1=address)
        _set_location_values(location, request.data)
        _normalize_location_uniqueness(location)
        location.save()

        # Preserve compatibility with the existing request prefill path.
        if location.kind == UserLocation.Kind.HOME:
            legacy, _ = CustomerSettings.objects.get_or_create(user=request.user)
            legacy.default_address = location.formatted_address
            legacy.default_zip = location.postal_code
            legacy.save(update_fields=["default_address", "default_zip", "updated_at"])
        return Response(_location_payload(location), status=status.HTTP_201_CREATED)


class IdentityLocationDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, location_id):
        return UserLocation.objects.filter(user=request.user, id=location_id).first()

    @transaction.atomic
    def patch(self, request, location_id):
        location = self._get(request, location_id)
        if not location:
            return Response({"detail": "Location not found."}, status=status.HTTP_404_NOT_FOUND)
        _set_location_values(location, request.data)
        _normalize_location_uniqueness(location)
        location.save()
        if location.kind == UserLocation.Kind.HOME:
            legacy, _ = CustomerSettings.objects.get_or_create(user=request.user)
            legacy.default_address = location.formatted_address
            legacy.default_zip = location.postal_code
            legacy.save(update_fields=["default_address", "default_zip", "updated_at"])
        return Response(_location_payload(location))

    def delete(self, request, location_id):
        location = self._get(request, location_id)
        if not location:
            return Response(status=status.HTTP_204_NO_CONTENT)
        location.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CurrentLocationContextAPIView(APIView):
    """Validates device coordinates without persisting live location.

    Current location is intentionally transient. Clients may pass this context to
    weather, traffic, discovery or ticket creation without overwriting Home.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            latitude = float(request.data.get("latitude"))
            longitude = float(request.data.get("longitude"))
        except (TypeError, ValueError):
            return Response({"detail": "Valid latitude and longitude are required."}, status=status.HTTP_400_BAD_REQUEST)
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return Response({"detail": "Coordinates are outside valid ranges."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "latitude": latitude,
            "longitude": longitude,
            "captured_at": timezone.now().isoformat(),
            "persisted": False,
            "replaces_home": False,
            "usage": "Current location may be used for weather, traffic, nearby discovery and explicit service-location overrides.",
        })


def _can_manage_business(user, business: Business) -> bool:
    if business.owner_id == user.id or getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False):
        return True
    return BusinessMember.objects.filter(business=business, user=user, is_active=True, can_manage_settings=True).exists()


def _trust_payload(business: Business, verification: BusinessVerification) -> dict:
    checks = verification.public_checks()
    verified_count = sum(1 for value in checks.values() if value)
    return {
        "business": {
            "id": business.id,
            "name": business.name,
            "logo_url": business.logo.url if business.logo else None,
            "business_email": business.business_email,
            "phone": business.phone,
        },
        "verification": {
            "status": verification.status,
            "checks": checks,
            "verified_count": verified_count,
            "total_checks": len(checks),
            "submitted_at": verification.submitted_at.isoformat() if verification.submitted_at else None,
            "verified_at": verification.verified_at.isoformat() if verification.verified_at else None,
            "disclaimer": "Verification confirms only the checks shown. It is not a guarantee or endorsement of service quality.",
        },
        "self_reported": {
            "licensed": bool(business.is_licensed),
            "insured": bool(business.is_insured),
            "bonded": bool(business.is_bonded),
            "background_checked": bool(business.background_checked),
        },
    }


class BusinessTrustAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, business_id):
        business = Business.objects.filter(id=business_id, is_active=True).first()
        if not business:
            return Response({"detail": "Business not found."}, status=status.HTTP_404_NOT_FOUND)
        verification, _ = BusinessVerification.objects.get_or_create(business=business)
        return Response(_trust_payload(business, verification))

    @transaction.atomic
    def patch(self, request, business_id):
        business = Business.objects.filter(id=business_id, is_active=True).first()
        if not business:
            return Response({"detail": "Business not found."}, status=status.HTTP_404_NOT_FOUND)
        if not _can_manage_business(request.user, business):
            return Response({"detail": "You do not have permission to manage this verification."}, status=status.HTTP_403_FORBIDDEN)
        verification, _ = BusinessVerification.objects.get_or_create(business=business)
        action = str(request.data.get("action") or "").upper()
        if action == "SUBMIT":
            verification.status = BusinessVerification.Status.IN_REVIEW
            verification.submitted_at = timezone.now()
            verification.save(update_fields=["status", "submitted_at", "updated_at"])
        elif action == "RESET" and (getattr(request.user, "is_platform_admin", False) or getattr(request.user, "is_superuser", False)):
            verification.status = BusinessVerification.Status.UNVERIFIED
            verification.save(update_fields=["status", "updated_at"])
        return Response(_trust_payload(business, verification))
