from django.urls import path

from .assistant_connection_views import SyncAssistantGeocodeView, SyncAssistantInboxStateView
from .assistant_daily_state_views import SyncAssistantDailyStateView, SyncAssistantDepartureReminderView
from .briefing_views import SyncGodModeBriefingView, SyncRoleAwareBriefingView
from .jarvis_product_views import (
    UserJarvisCheckInView,
    UserJarvisCheckOutView,
    UserJarvisCheckoutView,
    UserJarvisPortalView,
    UserJarvisProfileView,
    UserJarvisWebhookView,
    UserSyncAssistantLiveCheckoutView,
)
from .notification_views import SyncNotificationRefreshView, SyncNotificationSettingsView, SyncPushDeviceView
from .views import SyncAIActionDraftView, SyncAIChatView, SyncAIStatusView, SyncAITicketReplyExecuteView
from .voice_views import SyncVoiceStatusView, SyncVoiceSynthesizeView

urlpatterns = [
    path("status/", SyncAIStatusView.as_view(), name="sync-ai-status"),
    path("chat/", SyncAIChatView.as_view(), name="sync-ai-chat"),
    path("briefing/", SyncRoleAwareBriefingView.as_view(), name="sync-role-aware-briefing"),
    path("briefing/god-mode/", SyncGodModeBriefingView.as_view(), name="sync-god-mode-briefing"),

    # Preferred customer-facing SYNC Assistant routes.
    path("assistant/profile/", UserJarvisProfileView.as_view(), name="sync-assistant-profile"),
    path("assistant/check-in/", UserJarvisCheckInView.as_view(), name="sync-assistant-check-in"),
    path("assistant/check-out/", UserJarvisCheckOutView.as_view(), name="sync-assistant-check-out"),
    path("assistant/daily-state/", SyncAssistantDailyStateView.as_view(), name="sync-assistant-daily-state"),
    path("assistant/location/geocode/", SyncAssistantGeocodeView.as_view(), name="sync-assistant-geocode"),
    path("assistant/inbox-state/", SyncAssistantInboxStateView.as_view(), name="sync-assistant-inbox-state"),
    path("assistant/notifications/", SyncNotificationSettingsView.as_view(), name="sync-assistant-notifications"),
    path("assistant/notifications/refresh/", SyncNotificationRefreshView.as_view(), name="sync-assistant-notifications-refresh"),
    path("assistant/notifications/device/", SyncPushDeviceView.as_view(), name="sync-assistant-push-device"),
    path("assistant/calendar/<int:event_id>/departure-reminder/", SyncAssistantDepartureReminderView.as_view(), name="sync-assistant-departure-reminder"),
    path("assistant/billing/checkout/", UserJarvisCheckoutView.as_view(), name="sync-assistant-checkout"),
    path("assistant/billing/live/checkout/", UserSyncAssistantLiveCheckoutView.as_view(), name="sync-assistant-live-checkout"),
    path("assistant/billing/portal/", UserJarvisPortalView.as_view(), name="sync-assistant-portal"),
    path("assistant/billing/webhook/", UserJarvisWebhookView.as_view(), name="sync-assistant-webhook"),

    # Backward-compatible legacy routes. Existing clients keep working while UI copy moves to SYNC Assistant.
    path("jarvis/profile/", UserJarvisProfileView.as_view(), name="user-jarvis-profile"),
    path("jarvis/check-in/", UserJarvisCheckInView.as_view(), name="user-jarvis-check-in"),
    path("jarvis/check-out/", UserJarvisCheckOutView.as_view(), name="user-jarvis-check-out"),
    path("jarvis/billing/checkout/", UserJarvisCheckoutView.as_view(), name="user-jarvis-checkout"),
    path("jarvis/billing/portal/", UserJarvisPortalView.as_view(), name="user-jarvis-portal"),
    path("jarvis/billing/webhook/", UserJarvisWebhookView.as_view(), name="user-jarvis-webhook"),

    path("voice/status/", SyncVoiceStatusView.as_view(), name="sync-voice-status"),
    path("voice/synthesize/", SyncVoiceSynthesizeView.as_view(), name="sync-voice-synthesize"),
    path("actions/prepare/", SyncAIActionDraftView.as_view(), name="sync-ai-action-prepare"),
    path("actions/ticket-reply/execute/", SyncAITicketReplyExecuteView.as_view(), name="sync-ai-ticket-reply-execute"),
]
