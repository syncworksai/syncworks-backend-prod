"""Private Forge profile and conversation APIs, separate from Chief of Staff."""
from __future__ import annotations

from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from customer_health.models import ForgeConversationEntry, ForgePersonalProfile

OWNER_EMAIL = "jacoblord7@outlook.com"
FOCUS_AREAS = {
    "stoicism", "self-discipline", "confidence", "emotional-awareness",
    "critical-thinking", "leadership", "relationships", "athletic-mindset",
    "humility", "purpose", "financial-discipline",
}
STYLES = {"balanced", "challenging", "reflective"}


def allowed(user):
    return bool(user.is_authenticated and str(getattr(user, "email", "") or "").strip().lower() == OWNER_EMAIL)


def serialized_profile(profile):
    return {
        "focus_areas": profile.focus_areas,
        "approach": profile.coaching_style,
        "personal_vision": profile.personal_vision,
        "current_challenge": profile.current_challenge,
        "daily_practice": profile.daily_practice,
        "memory_enabled": profile.memory_enabled,
        "assessment_completed": profile.assessment_completed,
        "updated_at": profile.updated_at.isoformat(),
    }


class ForgeProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not allowed(request.user):
            return Response({"detail": "Private Forge pilot only."}, status=403)
        profile, _ = ForgePersonalProfile.objects.get_or_create(user=request.user)
        return Response(serialized_profile(profile))

    def patch(self, request):
        if not allowed(request.user):
            return Response({"detail": "Private Forge pilot only."}, status=403)
        data = request.data
        if not isinstance(data, dict):
            return Response({"detail": "Expected a profile object."}, status=400)
        fields = {"focus_areas", "approach", "personal_vision", "current_challenge",
                  "daily_practice", "memory_enabled", "assessment_completed"}
        if not set(data).issubset(fields):
            return Response({"detail": "Unrecognized profile field."}, status=400)
        if "focus_areas" in data:
            areas = data["focus_areas"]
            if not isinstance(areas, list) or len(areas) > 8 or len(areas) != len(set(str(x) for x in areas)) or any(not isinstance(a, str) or a not in FOCUS_AREAS for a in areas):
                return Response({"detail": "Select up to eight valid learning areas."}, status=400)
        if "approach" in data and data["approach"] not in STYLES:
            return Response({"detail": "Invalid coaching style."}, status=400)
        for field in ("personal_vision", "current_challenge", "daily_practice"):
            if field in data and (not isinstance(data[field], str) or len(data[field]) > 1500):
                return Response({"detail": f"{field} must be at most 1500 characters."}, status=400)
        for field in ("memory_enabled", "assessment_completed"):
            if field in data and not isinstance(data[field], bool):
                return Response({"detail": f"{field} must be true or false."}, status=400)
        with transaction.atomic():
            profile, _ = ForgePersonalProfile.objects.select_for_update().get_or_create(user=request.user)
            for field in ("focus_areas", "personal_vision", "current_challenge", "daily_practice", "memory_enabled", "assessment_completed"):
                if field in data:
                    setattr(profile, field, data[field])
            if "approach" in data:
                profile.coaching_style = data["approach"]
            profile.save()
            if not profile.memory_enabled:
                # Disabling memory means no saved conversations remain.
                ForgeConversationEntry.objects.filter(user=request.user).delete()
        return Response(serialized_profile(profile))

    def delete(self, request):
        if not allowed(request.user):
            return Response({"detail": "Private Forge pilot only."}, status=403)
        with transaction.atomic():
            ForgeConversationEntry.objects.filter(user=request.user).delete()
            ForgePersonalProfile.objects.filter(user=request.user).delete()
        return Response(status=204)


class ForgeHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not allowed(request.user):
            return Response({"detail": "Private Forge pilot only."}, status=403)
        chapter = str(request.query_params.get("chapter", "") or "")[:100]
        if not chapter:
            return Response({"detail": "chapter query is required."}, status=400)
        profile = ForgePersonalProfile.objects.filter(user=request.user).first()
        if not profile or not profile.memory_enabled:
            return Response({"messages": [], "memory_enabled": False})
        rows = list(ForgeConversationEntry.objects.filter(
            user=request.user, chapter_key=chapter
        ).order_by("-id")[:30])
        rows.reverse()
        return Response({
            "memory_enabled": True,
            "messages": [{"role": x.role, "text": x.text, "id": x.id} for x in rows],
        })

    def delete(self, request):
        if not allowed(request.user):
            return Response({"detail": "Private Forge pilot only."}, status=403)
        chapter = str(request.query_params.get("chapter", "") or "")[:100]
        qs = ForgeConversationEntry.objects.filter(user=request.user)
        if chapter:
            qs = qs.filter(chapter_key=chapter)
        count, _ = qs.delete()
        return Response({"deleted": count})
