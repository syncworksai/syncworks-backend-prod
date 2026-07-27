from django.urls import path

from .views import SyncAIChatView, SyncAIStatusView

urlpatterns = [
    path("status/", SyncAIStatusView.as_view(), name="sync-ai-status"),
    path("chat/", SyncAIChatView.as_view(), name="sync-ai-chat"),
]
