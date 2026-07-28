from __future__ import annotations

import os
import time

from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from user_accounts.models import AuditLog

from .voice import (
    SyncVoiceConfigurationError,
    SyncVoiceProviderError,
    configured_model_id,
    configured_voice_id,
    elevenlabs_configured,
    synthesize_sync_voice,
)


class SyncVoiceThrottle(UserRateThrottle):
    scope = "sync_ai"

    def get_rate(self):
        return (os.getenv("ELEVENLABS_SYNC_RATE_LIMIT") or "20/hour").strip()


class SyncVoiceStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "configured": elevenlabs_configured(),
                "provider": "elevenlabs",
                "voice_id": configured_voice_id(),
                "model": configured_model_id(),
                "browser_fallback": True,
            }
        )


class SyncVoiceSynthesizeView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [SyncVoiceThrottle]

    def post(self, request):
        text = str(request.data.get("text") or "").strip()
        if not text:
            return Response(
                {"detail": "text is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(text) > 10000:
            return Response(
                {"detail": "text is too long"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        started = time.monotonic()
        metadata = {
            "feature": "sync_voice",
            "provider": "elevenlabs",
            "voice_id": configured_voice_id(),
            "model": configured_model_id(),
            "user_id": str(request.user.id),
            "character_count": len(text),
        }

        try:
            audio = synthesize_sync_voice(text)
        except SyncVoiceConfigurationError as exc:
            AuditLog.objects.create(
                actor=request.user,
                action="sync_voice.configuration_error",
                metadata={**metadata, "error": str(exc)[:240]},
            )
            return Response(
                {
                    "detail": "SYNC premium voice is not configured.",
                    "browser_fallback": True,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except SyncVoiceProviderError as exc:
            AuditLog.objects.create(
                actor=request.user,
                action="sync_voice.provider_error",
                metadata={**metadata, "error": str(exc)[:240]},
            )
            return Response(
                {
                    "detail": "SYNC premium voice is temporarily unavailable.",
                    "browser_fallback": True,
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        latency_ms = round((time.monotonic() - started) * 1000)
        AuditLog.objects.create(
            actor=request.user,
            action="sync_voice.completed",
            metadata={
                **metadata,
                "request_id": audio.request_id,
                "character_cost": audio.character_cost,
                "latency_ms": latency_ms,
            },
        )

        response = HttpResponse(audio.content, content_type=audio.content_type)
        response["Content-Disposition"] = 'inline; filename="sync-summary.mp3"'
        response["Cache-Control"] = "no-store"
        response["X-SYNC-Voice-ID"] = audio.voice_id
        response["X-SYNC-Voice-Model"] = audio.model_id
        return response
