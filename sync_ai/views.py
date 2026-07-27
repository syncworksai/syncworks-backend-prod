from __future__ import annotations

import os
import time

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from user_accounts.models import AuditLog

from .context import build_instructions, resolve_workspace
from .service import (
    SyncAIConfigurationError,
    SyncAIProviderError,
    ai_enabled,
    configured_model,
    create_sync_response,
)


class SyncAIThrottle(UserRateThrottle):
    scope = "sync_ai"

    def get_rate(self):
        return (os.getenv("OPENAI_SYNC_RATE_LIMIT") or "30/hour").strip()


class SyncAIStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "enabled": ai_enabled(),
                "configured": bool((os.getenv("OPENAI_API_KEY") or "").strip()),
                "model": configured_model(),
                "workspaces": ["personal", "business"],
            }
        )


class SyncAIChatView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [SyncAIThrottle]

    def post(self, request):
        message = str(request.data.get("message") or "").strip()
        workspace = str(request.data.get("workspace") or "personal").strip().lower()
        business_id = request.headers.get("X-Business-ID") or request.data.get("business_id")

        if not message:
            return Response(
                {"detail": "message is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(message) > 6000:
            return Response(
                {"detail": "message is too long"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            context = resolve_workspace(
                user=request.user,
                workspace=workspace,
                business_id=str(business_id) if business_id else None,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        started = time.monotonic()
        base_metadata = {
            "feature": "sync_chat",
            "workspace": context.workspace,
            "role": context.role,
            "user_id": str(request.user.id),
            "business_id": str(context.business.id) if context.business else "",
        }

        try:
            result = create_sync_response(
                user_id=request.user.id,
                message=message,
                instructions=build_instructions(context),
                metadata=base_metadata,
            )
        except SyncAIConfigurationError as exc:
            AuditLog.objects.create(
                actor=request.user,
                action="sync_ai.configuration_error",
                metadata={**base_metadata, "error": str(exc)[:240]},
            )
            return Response(
                {"detail": "SYNC AI is not available yet."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except SyncAIProviderError as exc:
            AuditLog.objects.create(
                actor=request.user,
                action="sync_ai.provider_error",
                metadata={**base_metadata, "error": str(exc)[:240]},
            )
            return Response(
                {"detail": "SYNC could not complete that request. Please try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        latency_ms = round((time.monotonic() - started) * 1000)
        AuditLog.objects.create(
            actor=request.user,
            action="sync_ai.completed",
            metadata={
                **base_metadata,
                "model": result.model,
                "response_id": result.response_id,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
                "latency_ms": latency_ms,
            },
        )

        return Response(
            {
                "message": result.text,
                "workspace": context.workspace,
                "model": result.model,
                "usage": {
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "total_tokens": result.total_tokens,
                },
            }
        )
