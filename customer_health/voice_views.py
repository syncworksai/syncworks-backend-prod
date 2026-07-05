from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

ELEVENLABS_TTS_URL = (
    "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
)

ALLOWED_EVENT_TYPES = {
    "voice_preview",
    "daily_plan_summary",
    "workout_welcome",
    "exercise_intro",
    "set_countdown",
    "mid_set_encouragement",
    "final_reps",
    "set_completed",
    "rest_started",
    "rest_halfway",
    "rest_ending",
    "increase_weight",
    "hold_weight",
    "decrease_weight",
    "form_warning",
    "fatigue_response",
    "pain_response",
    "exercise_swap",
    "workout_completed",
    "recovery_day",
}

ENERGY_SETTINGS: dict[str, dict[str, Any]] = {
    "calm": {
        "stability": 0.72,
        "similarity_boost": 0.78,
        "style": 0.18,
        "use_speaker_boost": True,
        "speed": 0.94,
    },
    "balanced": {
        "stability": 0.58,
        "similarity_boost": 0.80,
        "style": 0.38,
        "use_speaker_boost": True,
        "speed": 1.0,
    },
    "high_energy": {
        "stability": 0.42,
        "similarity_boost": 0.82,
        "style": 0.68,
        "use_speaker_boost": True,
        "speed": 1.08,
    },
    "competition": {
        "stability": 0.36,
        "similarity_boost": 0.84,
        "style": 0.82,
        "use_speaker_boost": True,
        "speed": 1.10,
    },
}


def _setting(name: str, default: str = "") -> str:
    return str(getattr(settings, name, default) or default).strip()


def _secret_fingerprint(value: str) -> str:
    clean = str(value or "")
    return hashlib.sha256(
        clean.encode("utf-8")
    ).hexdigest()[:12]


def _voice_registry() -> dict[str, dict[str, str]]:
    return {
        "sync_fitness_coach": {
            "id": _setting(
                "ELEVENLABS_HEALTH_VOICE_ID",
                "4RkE9xiCb4LF4Wd7R4Sp",
            ),
            "name": _setting(
                "ELEVENLABS_HEALTH_VOICE_NAME",
                "SYNC Fitness Coach",
            ),
        },
    }


def _model_id() -> str:
    configured = _setting(
        "ELEVENLABS_MODEL_ID",
        "eleven_multilingual_v2",
    )
    if (
        configured.startswith("<")
        or "selected during implementation" in configured.lower()
    ):
        return "eleven_multilingual_v2"
    return configured


def _allow_request(user_id: Any) -> bool:
    limit = int(
        getattr(
            settings,
            "ELEVENLABS_HEALTH_REQUESTS_PER_MINUTE",
            20,
        )
        or 20
    )
    key = f"health-voice-user:{user_id}"
    try:
        current = cache.get(key)
        if current is None:
            cache.set(key, 1, timeout=60)
            return True
        if int(current) >= limit:
            return False
        cache.incr(key)
        return True
    except Exception:
        logger.exception("Health voice rate-limit cache failed.")
        return True


class HealthVoiceSpeakView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        text = str(request.data.get("text") or "").strip()
        event_type = str(
            request.data.get("event_type") or ""
        ).strip().lower()
        energy = str(
            request.data.get("energy") or "high_energy"
        ).strip().lower()
        voice_key = str(
            request.data.get("voice_key") or "sync_fitness_coach"
        ).strip().lower()

        if not text:
            return Response(
                {
                    "detail": "Coaching text is required.",
                    "code": "voice_text_required",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        max_characters = int(
            getattr(
                settings,
                "ELEVENLABS_HEALTH_MAX_CHARACTERS",
                600,
            )
            or 600
        )

        if len(text) > max_characters:
            return Response(
                {
                    "detail": (
                        "Coaching text must be "
                        f"{max_characters} characters or fewer."
                    ),
                    "code": "voice_text_too_long",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if event_type not in ALLOWED_EVENT_TYPES:
            return Response(
                {
                    "detail": "Unsupported Health coaching event.",
                    "code": "voice_event_not_allowed",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if energy not in ENERGY_SETTINGS:
            return Response(
                {
                    "detail": "Unsupported coach energy setting.",
                    "code": "voice_energy_not_allowed",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        voice = _voice_registry().get(voice_key)
        if not voice or not voice.get("id"):
            return Response(
                {
                    "detail": "Requested coach voice is unavailable.",
                    "code": "voice_not_available",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        api_key = _setting("ELEVENLABS_API_KEY")
        if not api_key:
            return Response(
                {
                    "detail": (
                        "ElevenLabs voice is not configured "
                        "on the backend."
                    ),
                    "code": "elevenlabs_not_configured",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if not _allow_request(request.user.pk):
            return Response(
                {
                    "detail": (
                        "Voice request limit reached. "
                        "Please wait a moment."
                    ),
                    "code": "voice_rate_limited",
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        timeout_seconds = int(
            getattr(settings, "ELEVENLABS_TIMEOUT_SECONDS", 20)
            or 20
        )
        output_format = _setting(
            "ELEVENLABS_OUTPUT_FORMAT",
            "mp3_44100_128",
        )
        url = ELEVENLABS_TTS_URL.format(voice_id=voice["id"])

        try:
            upstream = requests.post(
                url,
                params={"output_format": output_format},
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={
                    "text": text,
                    "model_id": _model_id(),
                    "voice_settings": ENERGY_SETTINGS[energy],
                },
                timeout=timeout_seconds,
            )
        except requests.Timeout:
            return Response(
                {
                    "detail": (
                        "The coach voice took too long to respond. "
                        "Use browser voice fallback."
                    ),
                    "code": "elevenlabs_timeout",
                },
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except requests.RequestException:
            logger.exception(
                "ElevenLabs Health voice request failed."
            )
            return Response(
                {
                    "detail": (
                        "The coach voice is temporarily unavailable. "
                        "Use browser voice fallback."
                    ),
                    "code": "elevenlabs_unavailable",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if not upstream.ok:
            upstream_body = upstream.text[:1200]
            request_id = (
                upstream.headers.get("request-id")
                or upstream.headers.get("x-request-id")
                or ""
            )
            env_key = str(
                os.environ.get("ELEVENLABS_API_KEY", "")
                or ""
            ).strip()

            logger.warning(
                (
                    "ElevenLabs Health voice failed. "
                    "status=%s request_id=%s "
                    "voice_id=%s model_id=%s "
                    "settings_key_length=%s "
                    "settings_key_fingerprint=%s "
                    "env_key_length=%s "
                    "env_key_fingerprint=%s "
                    "same_key=%s response=%s"
                ),
                upstream.status_code,
                request_id or "none",
                voice["id"],
                _model_id(),
                len(api_key),
                _secret_fingerprint(api_key),
                len(env_key),
                _secret_fingerprint(env_key),
                api_key == env_key,
                upstream_body,
            )
            return Response(
                {
                    "detail": (
                        "The coach voice could not be generated. "
                        "Use browser voice fallback."
                    ),
                    "code": "elevenlabs_generation_failed",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        response = HttpResponse(
            upstream.content,
            content_type=(
                upstream.headers.get("Content-Type")
                or "audio/mpeg"
            ),
            status=status.HTTP_200_OK,
        )
        response["Cache-Control"] = "private, max-age=300"
        response["X-SyncWorks-Voice-Key"] = voice_key
        response["X-SyncWorks-Voice-Name"] = voice["name"]
        response["X-SyncWorks-Voice-Energy"] = energy

        request_id = upstream.headers.get("request-id")
        if request_id:
            response["X-ElevenLabs-Request-Id"] = request_id

        return response


class HealthVoiceOptionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        voices = [
            {
                "key": key,
                "name": voice["name"],
                "available": bool(voice["id"]),
            }
            for key, voice in _voice_registry().items()
        ]

        return Response(
            {
                "default_voice_key": "sync_fitness_coach",
                "default_energy": "high_energy",
                "voices": voices,
                "energy_options": [
                    {"key": "calm", "label": "Calm"},
                    {"key": "balanced", "label": "Balanced"},
                    {"key": "high_energy", "label": "High Energy"},
                    {"key": "competition", "label": "Competition"},
                ],
                "model_id": _model_id(),
                "provider": "elevenlabs",
            }
        )