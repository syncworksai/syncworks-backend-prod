# backend/user_accounts/viewsets/ticket_calendar.py
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from user_accounts.services.calendar_sync import sync_ticket_for_user


class TicketCalendarMixin:
    """
    Mixin for TicketViewSet:
    POST /tickets/{id}/calendar_sync/
    Syncs the ticket to the CURRENT USER'S connected calendars.
    """

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def calendar_sync(self, request, pk=None):
        ticket = self.get_object()
        result = sync_ticket_for_user(ticket, request.user)
        status = 200 if result.get("ok") else 400
        return Response(result, status=status)
