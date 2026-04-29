from django.contrib import admin

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


@admin.register(PlatformCampaign)
class PlatformCampaignAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "status", "budget_cents", "created_at")
    search_fields = ("name", "objective")


@admin.register(PlatformContent)
class PlatformContentAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "campaign", "scheduled_for", "published_at")
    search_fields = ("title", "body")


@admin.register(PlatformLead)
class PlatformLeadAdmin(admin.ModelAdmin):
    list_display = ("id", "full_name", "email", "status", "score", "source", "last_activity_at")
    search_fields = ("full_name", "email", "phone", "external_id")


@admin.register(PlatformConversation)
class PlatformConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "lead", "channel", "status", "last_message_at")
    search_fields = ("external_thread_id",)


@admin.register(PlatformMessage)
class PlatformMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "direction", "sent_at")
    search_fields = ("external_message_id", "text")


@admin.register(PlatformAutomationFlow)
class PlatformAutomationFlowAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "trigger", "event_type", "is_active", "last_run_at")
    search_fields = ("name", "trigger", "event_type")


@admin.register(PlatformActivationEvent)
class PlatformActivationEventAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "event_type", "external_id", "processed_at", "created_at")
    search_fields = ("event_type", "external_id")


@admin.register(GrowthChannelConnection)
class GrowthChannelConnectionAdmin(admin.ModelAdmin):
    list_display = ("id", "provider", "account_label", "external_account_id", "status", "connected_at")
    search_fields = ("provider", "account_label", "external_account_id")


@admin.register(GrowthOAuthState)
class GrowthOAuthStateAdmin(admin.ModelAdmin):
    list_display = ("id", "provider", "status", "expires_at", "used_at", "created_at")
    search_fields = ("provider", "state")


@admin.register(GrowthOAuthToken)
class GrowthOAuthTokenAdmin(admin.ModelAdmin):
    list_display = ("id", "provider", "connection", "is_active", "expires_at", "created_at")
    search_fields = ("provider", "connection__external_account_id")


@admin.register(GrowthContentDraft)
class GrowthContentDraftAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "status", "source", "updated_at")
    search_fields = ("title", "body", "source")


@admin.register(GrowthContentQueueItem)
class GrowthContentQueueItemAdmin(admin.ModelAdmin):
    list_display = ("id", "draft", "channel_connection", "status", "scheduled_for", "posted_at")


@admin.register(GrowthAutomationRecipe)
class GrowthAutomationRecipeAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "trigger_type", "is_active", "last_run_at")
    search_fields = ("name", "trigger_type")


@admin.register(GrowthScheduledPostJob)
class GrowthScheduledPostJobAdmin(admin.ModelAdmin):
    list_display = ("id", "queue_item", "run_at", "status", "attempts", "last_attempt_at")