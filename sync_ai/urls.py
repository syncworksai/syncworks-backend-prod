from django.urls import path

from .views import (
    SyncAIActionDraftView,
    SyncAIChatView,
    SyncAIStatusView,
    SyncAITicketReplyExecuteView,
)

urlpatterns = [
    path("status/", SyncAIStatusView.as_view(), name="sync-ai-status"),
    path("chat/", SyncAIChatView.as_view(), name="sync-ai-chat"),
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
