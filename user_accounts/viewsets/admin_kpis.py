from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.response import Response

from django.contrib.auth import get_user_model

from user_accounts.permissions import IsPlatformOwner
from user_accounts.models import Ticket
from user_accounts.services.kpis import compute_kpis
from user_accounts.serializers.admin import AdminUserSerializer
from user_accounts.serializers.tickets import TicketSerializer

User = get_user_model()


class AdminKpiViewSet(viewsets.ViewSet):
    """
    Router-friendly KPI endpoint.

    GET /api/v1/admin/kpis/  -> list()
    """
    permission_classes = [IsPlatformOwner]

    def list(self, request):
        # Primary KPI source
        return Response(compute_kpis())


class AdminKpiAPIView(APIView):
    """
    Compatibility endpoint if you ever wire this with path().
    GET /api/v1/admin/kpis-view/
    """
    permission_classes = [IsPlatformOwner]

    def get(self, request, *args, **kwargs):
        return Response(compute_kpis())


class AdminTicketViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsPlatformOwner]
    queryset = Ticket.objects.all().order_by("-created_at")
    serializer_class = TicketSerializer


class AdminUserViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsPlatformOwner]
    queryset = User.objects.all().order_by("-date_joined")
    serializer_class = AdminUserSerializer
