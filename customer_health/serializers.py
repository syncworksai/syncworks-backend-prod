from __future__ import annotations

from rest_framework import serializers

from .models import CustomerHealthProfile


class CustomerHealthProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerHealthProfile
        fields = [
            "id",
            "profile_json",
            "snapshot_json",
            "workouts_json",
            "history_json",
            "progress_json",
            "devices_json",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def validate_profile_json(self, value):
        return value if isinstance(value, dict) else {}

    def validate_snapshot_json(self, value):
        return value if isinstance(value, dict) else {}

    def validate_workouts_json(self, value):
        return value if isinstance(value, list) else []

    def validate_history_json(self, value):
        return value if isinstance(value, list) else []

    def validate_progress_json(self, value):
        return value if isinstance(value, list) else []

    def validate_devices_json(self, value):
        return value if isinstance(value, list) else []


class RedeemHealthAccessCodeSerializer(serializers.Serializer):
    code = serializers.CharField(
        max_length=64,
        trim_whitespace=True,
    )

    def validate_code(self, value):
        code = str(value or "").strip().upper()

        if not code:
            raise serializers.ValidationError(
                "Enter a Health & Fitness access code."
            )

        return code

