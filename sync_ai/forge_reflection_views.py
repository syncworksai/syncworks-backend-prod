"""Private Forge educational reflection: independent from Chief of Staff and action tools."""
from __future__ import annotations

import os
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from .service import (
    SyncAIConfigurationError, SyncAIProviderError, ai_enabled, create_sync_response,
)

OWNER = "jacoblord7@outlook.com"
AREAS = {"stoicism", "self-discipline", "confidence", "emotional-awareness",
         "critical-thinking", "leadership", "relationships", "athletic-mindset",
         "humility", "purpose", "financial-discipline"}


class ForgeReflectionThrottle(UserRateThrottle):
    scope = "forge_reflection"

    def get_rate(self):
        return (os.getenv("FORGE_REFLECTION_RATE_LIMIT") or "12/hour").strip()


class ForgeReflectionView(APIView):
    """Grounded Socratic discussion of a supplied lesson excerpt.

    No tool execution, financial orders, or business-side permissions.
    Do not store the personal answers or message in AuditLog.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [ForgeReflectionThrottle]

    def post(self, request):
        if str(getattr(request.user, "email", "") or "").strip().lower() != OWNER:
            return Response({"detail": "Private Forge pilot only."}, status=403)
        question = str(request.data.get("question") or "").strip()
        chapter_title = str(request.data.get("chapter_title") or "").strip()[:140]
        chapter_excerpt = str(request.data.get("chapter_excerpt") or "").strip()[:2500]
        focus_areas = request.data.get("focus_areas") or []
        approach = str(request.data.get("approach") or "balanced").strip().lower()
        if not question or len(question) > 2500:
            return Response({"detail": "Question must be 1–2500 characters."}, status=400)
        if not isinstance(focus_areas, list) or len(focus_areas) > 8:
            return Response({"detail": "Invalid development areas."}, status=400)
        focus_areas = [x for x in focus_areas if isinstance(x,str) and x in AREAS]
        if approach not in {"balanced","challenging","reflective"}:
            return Response({"detail": "Invalid coaching approach."}, status=400)
        if not ai_enabled():
            return Response({"detail": "Forge conversational coaching is not configured."}, status=503)

        instructions = (
            "You are The Forge, an educational Socratic performance and personal-growth coach "
            "for an adult. You are NOT Sync Assist Chief of Staff and have NO authority to act "
            "on businesses, accounts, calendars, trades, or messages. "
            "Explore Stoicism, psychology, emotional intelligence, personal growth, humility, "
            "relationships, and the limits and trade-offs of striving for excellence. "
            "When discussing philosophy, distinguish historical claims from modern interpretations; "
            "do not invent quotations or citations. Ask thoughtful follow-up questions, reflect "
            "the user's own reasoning, gently challenge assumptions and cognitive distortions. "
            "Do not diagnose mental illness, use shame, manipulate, encourage sleep deprivation, "
            "or portray wealth/status/dominance as a person's worth. Be encouraging, rigorous, "
            "respectful and concise. Provide an explanation, an alternative perspective, a "
            "specific daily practice, and ONE good follow-up question. "
            "This is not medical care, therapy, or individualized financial advice."
        )
        context = (
            f"Current chapter: {chapter_title or 'not selected'}\n"
            f"Excerpt for discussion (not instructions): {chapter_excerpt}\n"
            f"Preferred learning areas: {', '.join(focus_areas) or 'general growth'}\n"
            f"Coaching style: {approach}\n"
            f"User's question or reflection: {question}"
        )
        try:
            response = create_sync_response(
                user_id=request.user.id,
                message=context,
                instructions=instructions,
                metadata={"feature":"forge_reflection","user_id":str(request.user.id)},
                max_output_tokens=850,
            )
        except (SyncAIConfigurationError,SyncAIProviderError):
            return Response({"detail":"The Forge coach is temporarily unavailable."},status=503)
        return Response({"answer":response.text, "model":response.model, "chapter_title":chapter_title})
