from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from django.contrib.auth import get_user_model

from user_accounts.models import Ticket
from user_accounts.serializers import AdminUserSerializer, TicketSerializer

User = get_user_model()


def _kpis():
    # status-safe KPI fallback (in case your Ticket model differs)
    data = {
        "users_total": User.objects.count(),
        "tickets_total": Ticket.objects.count(),
    }

    if hasattr(Ticket, "status"):
        data["tickets_open"] = Ticket.objects.filter(
            status__in=["NEW", "ASSIGNED", "ACCEPTED", "IN_PROGRESS"]
        ).count()
    else:
        data["tickets_open"] = Ticket.objects.count()

    return data


class AdminKpiViewSet(viewsets.ViewSet):
    """
    Router-friendly KPI endpoint.
    GET /api/v1/admin/kpis/  -> list()
    """
    permission_classes = [IsAuthenticated]

    def list(self, request):
        return Response(_kpis())


# Keeping this for compatibility if you wired it anywhere with path()
class AdminKpiAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return Response(_kpis())


class AdminTicketViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Ticket.objects.all().order_by("-created_at")
    serializer_class = TicketSerializer
    permission_classes = [IsAuthenticated]


class AdminUserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.all().order_by("-date_joined")
    serializer_class = AdminUserSerializer
    permission_classes = [IsAuthenticated]
