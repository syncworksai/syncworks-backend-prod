from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .local_intelligence import build_local_response, infer_local_intent


class SyncLocalIntelligenceView(APIView):
    """Resolve conversational nearby intent before the general AI chat path."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        message = str(request.data.get("message") or "").strip()
        if not message:
            return Response({"detail": "message is required"}, status=status.HTTP_400_BAD_REQUEST)
        if len(message) > 3000:
            return Response({"detail": "message is too long"}, status=status.HTTP_400_BAD_REQUEST)

        intent = infer_local_intent(message)
        if not intent:
            return Response({"handled": False, "intent": None})

        result = build_local_response(user=request.user, message=message, data=request.data) or {}
        return Response({"handled": True, **result})
