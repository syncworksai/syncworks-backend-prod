from __future__ import annotations

from copy import deepcopy

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import CustomerHealthProfile

ACTIVE_WORKOUT_KEY = "_active_workout"
MAX_WORKOUT_HISTORY = 500


def _profile_for_user(user, *, lock: bool = False) -> CustomerHealthProfile:
    queryset = CustomerHealthProfile.objects
    if lock:
        queryset = queryset.select_for_update()

    profile, _created = queryset.get_or_create(user=user)
    return profile


def _clean_session(value):
    return deepcopy(value) if isinstance(value, dict) else None


def _session_identity(session: dict) -> str:
    return str(
        session.get("id")
        or session.get("session_id")
        or session.get("client_session_id")
        or ""
    ).strip()


class HealthWorkoutSessionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _profile_for_user(request.user)
        history = profile.history_json if isinstance(profile.history_json, list) else []

        return Response(
            {
                "count": len(history),
                "results": history,
                "updated_at": profile.updated_at,
            },
            status=status.HTTP_200_OK,
        )

    @transaction.atomic
    def post(self, request):
        session = _clean_session(request.data.get("session"))
        if not session:
            return Response(
                {"detail": "A workout session object is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        session_id = _session_identity(session)
        if not session_id:
            return Response(
                {"detail": "Workout session id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        saved_at = timezone.now().isoformat()
        session["server_saved_at"] = saved_at
        session.setdefault("status", "completed")

        profile = _profile_for_user(request.user, lock=True)
        history = list(profile.history_json or [])

        next_history = [
            item
            for item in history
            if not (
                isinstance(item, dict)
                and _session_identity(item) == session_id
            )
        ]
        next_history.insert(0, session)
        next_history = next_history[:MAX_WORKOUT_HISTORY]

        snapshot = dict(profile.snapshot_json or {})
        active = snapshot.get(ACTIVE_WORKOUT_KEY)
        if isinstance(active, dict):
            active_session = active.get("session")
            if isinstance(active_session, dict) and _session_identity(active_session) == session_id:
                snapshot.pop(ACTIVE_WORKOUT_KEY, None)

        profile.history_json = next_history
        profile.snapshot_json = snapshot
        profile.save(update_fields=["history_json", "snapshot_json", "updated_at"])

        return Response(
            {
                "saved": True,
                "session": session,
                "count": len(next_history),
                "updated_at": profile.updated_at,
            },
            status=status.HTTP_200_OK,
        )


class HealthActiveWorkoutView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _profile_for_user(request.user)
        snapshot = dict(profile.snapshot_json or {})
        active = snapshot.get(ACTIVE_WORKOUT_KEY)

        return Response(
            {
                "active_workout": active if isinstance(active, dict) else None,
                "updated_at": profile.updated_at,
            },
            status=status.HTTP_200_OK,
        )

    @transaction.atomic
    def put(self, request):
        session = _clean_session(request.data.get("session"))
        if not session:
            return Response(
                {"detail": "An active workout session object is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        session_id = _session_identity(session)
        if not session_id:
            return Response(
                {"detail": "Workout session id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        state = {
            "session": session,
            "planner_item_id": str(request.data.get("planner_item_id") or ""),
            "workout_id": str(request.data.get("workout_id") or ""),
            "saved_at": timezone.now().isoformat(),
            "version": 1,
        }

        profile = _profile_for_user(request.user, lock=True)
        snapshot = dict(profile.snapshot_json or {})
        snapshot[ACTIVE_WORKOUT_KEY] = state
        profile.snapshot_json = snapshot
        profile.save(update_fields=["snapshot_json", "updated_at"])

        return Response(
            {
                "saved": True,
                "active_workout": state,
                "updated_at": profile.updated_at,
            },
            status=status.HTTP_200_OK,
        )

    @transaction.atomic
    def delete(self, request):
        profile = _profile_for_user(request.user, lock=True)
        snapshot = dict(profile.snapshot_json or {})
        existed = ACTIVE_WORKOUT_KEY in snapshot
        snapshot.pop(ACTIVE_WORKOUT_KEY, None)
        profile.snapshot_json = snapshot
        profile.save(update_fields=["snapshot_json", "updated_at"])

        return Response(
            {
                "cleared": existed,
                "updated_at": profile.updated_at,
            },
            status=status.HTTP_200_OK,
        )
