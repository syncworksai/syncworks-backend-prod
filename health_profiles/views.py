from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import HealthAthleteProfile
from .serializers import HealthAthleteProfileSerializer


def get_profile(user):
    profile, _ = HealthAthleteProfile.objects.get_or_create(user=user)
    return profile


def parse_expected_profile_version(request):
    raw = request.data.get("expected_profile_version")
    if raw in (None, ""):
        return None

    try:
        return int(raw)
    except (TypeError, ValueError):
        return "invalid"


def version_conflict_response(profile, expected_version):
    return Response(
        {
            "detail": "The athlete profile changed on another device or session.",
            "code": "profile_version_conflict",
            "expected_profile_version": expected_version,
            "current_profile_version": profile.profile_version,
            "profile": HealthAthleteProfileSerializer(profile).data,
        },
        status=status.HTTP_409_CONFLICT,
    )


def validate_expected_profile_version(request, profile):
    expected_version = parse_expected_profile_version(request)

    if expected_version == "invalid":
        return Response(
            {
                "detail": "expected_profile_version must be an integer.",
                "code": "invalid_profile_version",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if (
        expected_version is not None
        and expected_version != profile.profile_version
    ):
        return version_conflict_response(profile, expected_version)

    return None


class HealthAthleteProfileView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(HealthAthleteProfileSerializer(get_profile(request.user)).data)

    @transaction.atomic
    def patch(self, request):
        profile = (
            HealthAthleteProfile.objects.select_for_update()
            .get_or_create(user=request.user)[0]
        )

        conflict = validate_expected_profile_version(
            request, profile
        )
        if conflict:
            return conflict

        payload = request.data.copy()
        payload.pop("expected_profile_version", None)

        serializer = HealthAthleteProfileSerializer(
            profile, data=payload, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class HealthPlanControlView(APIView):
    permission_classes = (IsAuthenticated,)

    @transaction.atomic
    def post(self, request):
        profile = (
            HealthAthleteProfile.objects.select_for_update()
            .get_or_create(user=request.user)[0]
        )

        conflict = validate_expected_profile_version(
            request, profile
        )
        if conflict:
            return conflict

        action = str(request.data.get("action", "")).strip().lower()

        allowed = {"review", "rebuild", "restart_keep_weights", "reset"}
        if action not in allowed:
            return Response(
                {"detail": "Unsupported plan-control action."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        confirmed = bool(request.data.get("confirmed", False))
        if action == "reset" and not confirmed:
            return Response(
                {"detail": "Reset requires explicit confirmation.", "confirmation_required": True},
                status=status.HTTP_409_CONFLICT,
            )

        now = timezone.now()
        profile.requires_plan_review = action in {"review", "rebuild", "restart_keep_weights"}

        if action == "restart_keep_weights":
            profile.last_plan_restart_at = now
            profile.plan_preferences = {
                **profile.plan_preferences,
                "restart_requested": True,
                "preserve_working_weights": True,
                "requested_at": now.isoformat(),
            }

        if action == "reset":
            profile.last_plan_reset_at = now
            profile.plan_preferences = {
                "reset_requested": True,
                "confirmed": True,
                "requested_at": now.isoformat(),
            }
            profile.simulation_preferences = {}

        profile.profile_version += 1
        profile.save()

        return Response({
            "action": action,
            "accepted": True,
            "profile": HealthAthleteProfileSerializer(profile).data,
        })


class HealthSimulationPreferencesView(APIView):
    permission_classes = (IsAuthenticated,)

    @transaction.atomic
    def patch(self, request):
        profile = (
            HealthAthleteProfile.objects.select_for_update()
            .get_or_create(user=request.user)[0]
        )

        conflict = validate_expected_profile_version(
            request, profile
        )
        if conflict:
            return conflict

        preferences = request.data.get(
            "simulation_preferences", request.data
        )

        if not isinstance(preferences, dict):
            return Response(
                {"detail": "Simulation preferences must be an object."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        allowed = {"weeks", "expected_adherence", "planned_sessions", "baseline_volume"}
        profile.simulation_preferences = {
            key: value for key, value in preferences.items() if key in allowed
        }
        profile.profile_version += 1
        profile.save()
        return Response(HealthAthleteProfileSerializer(profile).data)
