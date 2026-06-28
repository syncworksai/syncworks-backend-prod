from rest_framework import serializers

from user_accounts.models import OperationalAlert, OperationalEvent, TicketETA


class TicketETASerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketETA
        fields = [
            "id",
            "ticket",
            "window_start",
            "window_end",
            "estimated_arrival",
            "status",
            "delay_reason",
            "customer_message",
            "updated_by",
            "updated_at",
        ]
        read_only_fields = ["id", "ticket", "updated_by", "updated_at"]

    def validate(self, attrs):
        start = attrs.get("window_start", getattr(self.instance, "window_start", None))
        end = attrs.get("window_end", getattr(self.instance, "window_end", None))
        if start and end and end < start:
            raise serializers.ValidationError(
                {"window_end": "Arrival window end must be after its start."}
            )
        return attrs


class OperationalEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = OperationalEvent
        fields = [
            "id",
            "business",
            "ticket",
            "event_type",
            "visibility",
            "title",
            "message",
            "data",
            "occurred_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "business",
            "ticket",
            "occurred_at",
            "created_by",
        ]

    def validate_data(self, value):
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("data must be a JSON object.")
        return value


class OperationalAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = OperationalAlert
        fields = [
            "id",
            "event",
            "recipient",
            "audience",
            "channel",
            "status",
            "dedupe_key",
            "delivered_at",
            "read_at",
            "acknowledged_at",
            "failure_reason",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "event",
            "recipient",
            "dedupe_key",
            "delivered_at",
            "read_at",
            "acknowledged_at",
            "created_at",
        ]
