from django.contrib import admin

from platform_growth.models import (
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
