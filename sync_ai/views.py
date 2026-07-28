from __future__ import annotations

import os
import time

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from user_accounts.models import AuditLog

from .action_drafts import build_draft_prompt, get_draft_definition
from .context import build_instructions, resolve_workspace
from .execution import execute_ticket_reply
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


def _resolve_request_context(request):
    workspace = str(request.data.get("workspace") or "personal").strip().lower()
    business_id = request.headers.get("X-Business-ID") or request.data.get("business_id")
    return resolve_workspace(
        user=request.user,
        workspace=workspace,
        business_id=str(business_id) if business_id else None,
    )


def _provider_error_response(*, request, metadata, exc):
    action = (
        "sync_ai.configuration_error"
        if isinstance(exc, SyncAIConfigurationError)
        else "sync_ai.provider_error"
    )
    AuditLog.objects.create(
        actor=request.user,
        action=action,
        metadata={**metadata, "error": str(exc)[:240]},
    )
    if isinstance(exc, SyncAIConfigurationError):
        return Response(
            {"detail": "SYNC AI is not available yet."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response(
        {"detail": "SYNC could not complete that request. Please try again."},
        status=status.HTTP_502_BAD_GATEWAY,
    )


class SyncAIStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "enabled": ai_enabled(),
                "configured": bool((os.getenv("OPENAI_API_KEY") or "").strip()),
                "model": configured_model(),
                "workspaces": ["personal", "business"],
                "capabilities": {
                    "chat": True,
                    "read_only_context": True,
                    "draft_actions": [
                        "ticket_reply",
                        "lead_follow_up",
                        "schedule_proposal",
                    ],
                    "execution": {
                        "ticket_reply": True,
                        "lead_follow_up": False,
                        "schedule_change": False,
                        "assignment": False,
                        "payment": False,
                    },
                },
            }
        )


class SyncAIChatView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [SyncAIThrottle]

    def post(self, request):
        message = str(request.data.get("message") or "").strip()
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
            context = _resolve_request_context(request)
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
        except (SyncAIConfigurationError, SyncAIProviderError) as exc:
            return _provider_error_response(
                request=request,
                metadata=base_metadata,
                exc=exc,
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


class SyncAIActionDraftView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [SyncAIThrottle]

    def post(self, request):
        instruction = str(request.data.get("instruction") or "").strip()
        action_type = str(request.data.get("action_type") or "").strip().lower()

        if not instruction:
            return Response(
                {"detail": "instruction is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(instruction) > 3000:
            return Response(
                {"detail": "instruction is too long"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            context = _resolve_request_context(request)
            definition = get_draft_definition(action_type, context)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        started = time.monotonic()
        metadata = {
            "feature": "sync_action_draft",
            "action_type": definition.action_type,
            "workspace": context.workspace,
            "role": context.role,
            "user_id": str(request.user.id),
            "business_id": str(context.business.id) if context.business else "",
        }

        try:
            result = create_sync_response(
                user_id=request.user.id,
                message=build_draft_prompt(
                    definition=definition,
                    instruction=instruction,
                    context=context,
                ),
                instructions=build_instructions(context),
                metadata=metadata,
            )
        except (SyncAIConfigurationError, SyncAIProviderError) as exc:
            return _provider_error_response(
                request=request,
                metadata=metadata,
                exc=exc,
            )

        latency_ms = round((time.monotonic() - started) * 1000)
        AuditLog.objects.create(
            actor=request.user,
            action="sync_ai.action_draft_prepared",
            metadata={
                **metadata,
                "model": result.model,
                "response_id": result.response_id,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
                "latency_ms": latency_ms,
                "review_required": True,
                "executed": False,
            },
        )

        return Response(
            {
                "action_type": definition.action_type,
                "title": definition.title,
                "draft": result.text,
                "workspace": context.workspace,
                "status": "prepared",
                "review_required": True,
                "executed": False,
                "model": result.model,
                "usage": {
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "total_tokens": result.total_tokens,
                },
            }
        )


class SyncAITicketReplyExecuteView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [SyncAIThrottle]

    def post(self, request):
        body = str(request.data.get("body") or "").strip()
        confirmed = request.data.get("confirmed") is True
        raw_ticket_id = request.data.get("ticket_id")

        if not confirmed:
            return Response(
                {"detail": "Final confirmation is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not body:
            return Response(
                {"detail": "Reply body is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(body) > 6000:
            return Response(
                {"detail": "Reply body is too long."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            ticket_id = int(raw_ticket_id)
        except (TypeError, ValueError):
            return Response(
                {"detail": "A valid ticket_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            context = _resolve_request_context(request)
            message = execute_ticket_reply(
                user=request.user,
                context=context,
                ticket_id=ticket_id,
                body=body,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        return Response(
            {
                "status": "executed",
                "executed": True,
                "workspace": context.workspace,
                "ticket_id": message.ticket_id,
                "ticket_message_id": message.id,
                "body": message.body,
                "created_at": message.created_at.isoformat(),
            },
            status=status.HTTP_201_CREATED,
        )
