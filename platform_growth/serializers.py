from __future__ import annotations

from rest_framework import serializers

from platform_growth.models import (
    PlatformActivationEvent,
    PlatformAutomationFlow,
    PlatformCampaign,
    PlatformContent,
    PlatformConversation,
    PlatformLead,
    PlatformMessage,
)


class PlatformCampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformCampaign
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at", "created_by")


class PlatformContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformContent
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at", "created_by")


class PlatformLeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformLead
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at")


class PlatformMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformMessage
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at")


class PlatformConversationSerializer(serializers.ModelSerializer):
    messages = PlatformMessageSerializer(many=True, read_only=True)

    class Meta:
        model = PlatformConversation
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at", "last_message_at")


class PlatformAutomationFlowSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformAutomationFlow
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at", "created_by", "last_run_at")


class PlatformActivationEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformActivationEvent
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at", "processed_at")
