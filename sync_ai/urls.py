from django.urls import path

from .views import (
    SyncAIActionDraftView,
    SyncAIChatView,
    SyncAIStatusView,
    SyncAITicketReplyExecuteView,
)

from .voice_views import (
    SyncVoiceStatusView,
    SyncVoiceSynthesizeView,
)

urlpatterns = [
    path("status/", SyncAIStatusView.as_view(), name="sync-ai-status"),
    path("chat/", SyncAIChatView.as_view(), name="sync-ai-chat"),
    path(
        "voice/status/",
        SyncVoiceStatusView.as_view(),
        name="sync-voice-status",
    ),
    path(
        "voice/synthesize/",
        SyncVoiceSynthesizeView.as_view(),
        name="sync-voice-synthesize",
    ),
    path(
        "actions/prepare/",
        SyncAIActionDraftView.as_view(),
        name="sync-ai-action-prepare",
    ),
    path(
        "actions/ticket-reply/execute/",
        SyncAITicketReplyExecuteView.as_view(),
        name="sync-ai-ticket-reply-execute",
    ),
]
