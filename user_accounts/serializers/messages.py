from rest_framework import serializers
from user_accounts.models import TicketMessage, TicketAttachment


class TicketMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketMessage
        fields = ["id", "ticket", "sender", "body", "type", "created_at"]
        read_only_fields = ["sender", "created_at"]


class TicketAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketAttachment
        fields = ["id", "ticket", "uploaded_by", "file", "created_at"]
        read_only_fields = ["uploaded_by", "created_at"]
