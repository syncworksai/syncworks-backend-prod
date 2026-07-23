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


class HealthAthleteProfileView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(HealthAthleteProfileSerializer(get_profile(request.user)).data)

    def patch(self, request):
        profile = get_profile(request.user)
        serializer = HealthAthleteProfileSerializer(
            profile, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class HealthPlanControlView(APIView):
    permission_classes = (IsAuthenticated,)

    @transaction.atomic
    def post(self, request):
        profile = get_profile(request.user)
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

    def patch(self, request):
        profile = get_profile(request.user)
        preferences = request.data.get("simulation_preferences", request.data)

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
