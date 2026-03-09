from rest_framework import serializers
from user_accounts.models import Connection, InviteCode


class ConnectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Connection
        fields = "__all__"


class InviteCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = InviteCode
        fields = "__all__"
        read_only_fields = ["code", "uses", "created_at"]
