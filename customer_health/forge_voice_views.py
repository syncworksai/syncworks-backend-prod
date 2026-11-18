"""Founder-only Forge voice service. Separate from Health trainer entitlements."""
from __future__ import annotations

import logging

import requests
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .voice_views import (
    DEFAULT_HEALTH_VOICE_ID, ELEVENLABS_TTS_URL, ENERGY_SETTINGS,
    _model_id, _setting,
)

logger = logging.getLogger(__name__)
OWNER_EMAIL = "jacoblord7@outlook.com"
MAX_TEXT = 900

# Curated mature male narrators, selected from ElevenLabs voice discovery.
# Client sends a stable key, never an arbitrary voice ID or provider URL.
FORGE_VOICES = {
    "tucker": {"id": "EI3BL0ECeQayX8N4doHx", "name": "Tucker Thomas · deep American storyteller"},
    "ambrose": {"id": "gRPwZFYxBbXTrxXJzU6u", "name": "Father Ambrose · warm, reflective American"},
    "david": {"id": "BNgbHR0DNeZixGQVzloa", "name": "David · deep British narrator"},
}
DEFAULT_FORGE_VOICE = "tucker"


class ForgeVoiceSpeakView(APIView):
    """Speak short personalized text using backend ElevenLabs credentials.

    Does not expose an LLM, automate schedules, or grant Health AI access.
    Additional server-side entitlement controls are required before public release.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if str(getattr(request.user, "email", "") or "").strip().lower() != OWNER_EMAIL:
            return Response({"detail": "Forge is a private pilot."}, status=status.HTTP_403_FORBIDDEN)

        content = str(request.data.get("text") or "").strip()
        energy = str(request.data.get("energy") or "calm").strip().lower()
        voice_key = str(request.data.get("voice_key") or DEFAULT_FORGE_VOICE).strip().lower()
        if not content or len(content) > MAX_TEXT:
            return Response(
                {"detail": f"Text must contain 1–{MAX_TEXT} characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if energy not in ("calm", "balanced", "high_energy"):
            return Response({"detail": "Unsupported energy setting."}, status=status.HTTP_400_BAD_REQUEST)

        if voice_key not in FORGE_VOICES:
            return Response({"detail": "Unknown Forge narrator."}, status=400)

        key = _setting("ELEVENLABS_API_KEY")
        voice_id = FORGE_VOICES[voice_key]["id"]
        if not key or not voice_id:
            return Response(
                {"detail": "Forge natural voice is not configured.", "code": "forge_voice_unavailable"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        rate_key = f"forge-voice:{request.user.pk}"
        try:
            if not cache.add(rate_key, 1, timeout=60):
                count = int(cache.get(rate_key, 0))
                if count >= 10:
                    return Response({"detail": "Voice request limit reached."}, status=429)
                cache.incr(rate_key)
        except Exception:
            logger.exception("Forge voice rate limit cache unavailable")
            return Response({"detail": "Voice temporarily unavailable."}, status=503)

        try:
            upstream = requests.post(
                ELEVENLABS_TTS_URL.format(voice_id=voice_id),
                params={"output_format": _setting("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")},
                headers={
                    "xi-api-key": key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={
                    "text": content,
                    "model_id": _model_id(),
                    "voice_settings": ENERGY_SETTINGS[energy],
                },
                timeout=min(30, max(5, int(getattr(settings, "ELEVENLABS_TIMEOUT_SECONDS", 20) or 20))),
            )
            if not upstream.ok:
                logger.warning("Forge natural speech provider returned HTTP %s", upstream.status_code)
                return Response({"detail": "Natural speech is temporarily unavailable."}, status=502)
        except requests.RequestException:
            logger.exception("Forge natural speech provider failed")
            return Response({"detail": "Natural speech is temporarily unavailable."}, status=502)

        response = HttpResponse(upstream.content, content_type="audio/mpeg")
        response["Cache-Control"] = "private, no-store"
        response["X-SyncWorks-Voice-Provider"] = "elevenlabs"
        response["X-SyncWorks-Forge-Voice"] = voice_key
        return response
