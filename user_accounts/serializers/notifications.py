from __future__ import annotations

from rest_framework import serializers

from user_accounts.models import Notification, PlatformNewsItem


class NotificationSerializer(serializers.ModelSerializer):
    actor_display = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "recipient",
            "actor",
            "actor_display",
            "type",
            "title",
            "body",
            "data",
            "is_read",
            "read_at",
            "archived_at",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "read_at", "archived_at", "recipient", "actor"]

    def get_actor_display(self, obj: Notification) -> str:
        a = getattr(obj, "actor", None)
        if not a:
            return ""
        return a.first_name or a.username or a.email or ""


class PlatformNewsItemSerializer(serializers.ModelSerializer):
    is_live = serializers.SerializerMethodField()

    class Meta:
        model = PlatformNewsItem
        fields = [
            "id",
            "kind",
            "title",
            "body",
            "image",
            "link_url",
            "is_active",
            "starts_at",
            "ends_at",
            "target_scope",
            "target_zip_codes",
            "is_live",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "is_live"]

    def get_is_live(self, obj: PlatformNewsItem) -> bool:
        return obj.is_live()
