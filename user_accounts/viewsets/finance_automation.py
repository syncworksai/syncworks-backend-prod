from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models.personal_finance import FinanceConnection
from user_accounts.services.finance_intelligence import build_finance_briefing, infer_recurring_obligations
from user_accounts.services.plaid_finance import sync_connection


class FinanceAutomationViewSet(viewsets.ViewSet):
    """Finance intelligence endpoints shared by the dashboard and SYNC Assist."""

    permission_classes = [IsAuthenticated]

    def list(self, request):
        return Response(build_finance_briefing(request.user))

    @action(detail=False, methods=["post"], url_path="refresh")
    def refresh(self, request):
        synced = 0
        errors = []

        connections = FinanceConnection.objects.filter(
            user=request.user,
            status=FinanceConnection.Status.ACTIVE,
        )
        for connection in connections:
            try:
                sync_connection(connection)
                synced += 1
            except Exception as exc:
                errors.append({"connection_id": connection.id, "detail": str(exc)})

        recurring = infer_recurring_obligations(request.user)
        payload = {
            "synced_connections": synced,
            "connection_errors": errors,
            "recurring": recurring,
            "briefing": build_finance_briefing(request.user),
        }
        return Response(payload, status=status.HTTP_200_OK)
