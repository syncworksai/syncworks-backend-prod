from rest_framework import viewsets
from user_accounts.models import Connection, InviteCode
from user_accounts.serializers.connections import ConnectionSerializer, InviteCodeSerializer


class ConnectionViewSet(viewsets.ModelViewSet):
    queryset = Connection.objects.all().order_by("-created_at")
    serializer_class = ConnectionSerializer


class InviteCodeViewSet(viewsets.ModelViewSet):
    queryset = InviteCode.objects.all().order_by("-created_at")
    serializer_class = InviteCodeSerializer

    def perform_create(self, serializer):
        serializer.save(code=InviteCode.generate_code(), created_by=self.request.user, sbo_user=self.request.user)
