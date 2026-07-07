from __future__ import annotations

from rest_framework import serializers

from .models import CustomerHealthFeedback, CustomerHealthProfile


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



class CustomerHealthFeedbackSerializer(serializers.ModelSerializer):
    user_email = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = CustomerHealthFeedback
        fields = [
            "id",
            "user_email",
            "client_feedback_id",
            "area",
            "severity",
            "message",
            "status",
            "source",
            "page_path",
            "runtime_json",
            "extra_json",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user_email",
            "status",
            "created_at",
            "updated_at",
        ]

    def get_user_email(self, obj):
        return getattr(obj.user, "email", "") or getattr(obj.user, "username", "")

    def validate_area(self, value):
        area = str(value or "General").strip()
        return area[:64] or "General"

    def validate_severity(self, value):
        severity = str(value or "Medium").strip()
        allowed = {"Low", "Medium", "High", "Blocking"}
        return severity if severity in allowed else "Medium"

    def validate_message(self, value):
        message = str(value or "").strip()

        if not message:
            raise serializers.ValidationError("Enter beta feedback before submitting.")

        if len(message) > 4000:
            raise serializers.ValidationError("Feedback must be 4,000 characters or fewer.")

        return message

    def validate_runtime_json(self, value):
        return value if isinstance(value, dict) else {}

    def validate_extra_json(self, value):
        return value if isinstance(value, dict) else {}

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

