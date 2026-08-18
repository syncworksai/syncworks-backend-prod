from rest_framework import serializers

from .communication_models import SocialMessage
from .serializers import SocialUserSerializer


class SocialMessageSerializer(serializers.ModelSerializer):
    sender_detail = SocialUserSerializer(source="sender", read_only=True)

    class Meta:
        model = SocialMessage
        fields = (
            "id", "group", "event", "sender", "sender_detail", "kind", "body",
            "edited_at", "deleted_at", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "sender", "sender_detail", "edited_at", "deleted_at",
            "created_at", "updated_at",
        )

    def validate_body(self, value):
        value = str(value or "").strip()
        if not value:
            raise serializers.ValidationError("Message cannot be empty.")
        return value
