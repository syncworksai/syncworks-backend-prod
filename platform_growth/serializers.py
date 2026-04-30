from __future__ import annotations

from rest_framework import serializers

from platform_growth.models import (
    GrowthAutomationRecipe,
    GrowthChannelConnection,
    GrowthContentDraft,
    GrowthContentQueueItem,
    GrowthOAuthState,
    GrowthOAuthToken,
    GrowthScheduledPostJob,
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


class GrowthChannelConnectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrowthChannelConnection
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at", "created_by")


class GrowthOAuthStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrowthOAuthState
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at", "created_by", "used_at")


class GrowthOAuthTokenSerializer(serializers.ModelSerializer):
    connection_external_account_id = serializers.CharField(source="connection.external_account_id", read_only=True)

    class Meta:
        model = GrowthOAuthToken
        fields = (
            "id",
            "connection",
            "connection_external_account_id",
            "provider",
            "token_type",
            "expires_at",
            "scope",
            "is_active",
            "metadata",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class GrowthContentDraftSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrowthContentDraft
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at", "created_by")


class GrowthContentQueueItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrowthContentQueueItem
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at", "created_by")


class GrowthAutomationRecipeSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrowthAutomationRecipe
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at", "created_by", "last_run_at")


class GrowthScheduledPostJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = GrowthScheduledPostJob
        fields = "__all__"
        read_only_fields = ("id", "created_at", "updated_at", "created_by", "attempts", "last_attempt_at", "last_error")
