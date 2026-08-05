from django.urls import path

from .briefing_views import SyncGodModeBriefingView, SyncRoleAwareBriefingView
from .jarvis_product_views import (
    UserJarvisCheckInView,
    UserJarvisCheckOutView,
    UserJarvisCheckoutView,
    UserJarvisPortalView,
    UserJarvisProfileView,
    UserJarvisWebhookView,
)
from .views import SyncAIActionDraftView, SyncAIChatView, SyncAIStatusView, SyncAITicketReplyExecuteView
from .voice_views import SyncVoiceStatusView, SyncVoiceSynthesizeView

urlpatterns = [
    path("status/", SyncAIStatusView.as_view(), name="sync-ai-status"),
    path("chat/", SyncAIChatView.as_view(), name="sync-ai-chat"),
    path("briefing/", SyncRoleAwareBriefingView.as_view(), name="sync-role-aware-briefing"),
    path("briefing/god-mode/", SyncGodModeBriefingView.as_view(), name="sync-god-mode-briefing"),
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
