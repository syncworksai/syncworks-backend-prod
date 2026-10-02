from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import AuditLog

from .drive_state import build_drive_state


class SyncAssistantDriveStateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        payload = build_drive_state(request.user)
        AuditLog.objects.create(
            actor=request.user,
            action="sync_assistant.drive_state.viewed",
            metadata={
                "local_date": payload.get("local_date"),
                "events": len(payload.get("events") or []),
                "messages": len(payload.get("messages") or []),
                "requests": len(payload.get("requests") or []),
            },
        )
        return Response(payload)
