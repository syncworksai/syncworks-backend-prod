from django.urls import include, path
from rest_framework.routers import DefaultRouter

from platform_growth.views import (
    GrowthAutomationRecipeViewSet,
    GrowthChannelConnectionViewSet,
    GrowthContentDraftViewSet,
    GrowthContentQueueItemViewSet,
    GrowthOAuthStateViewSet,
    GrowthOAuthTokenViewSet,
    GrowthScheduledPostJobViewSet,
    MetaWebhookEventAPIView,
    MetaWebhookVerificationAPIView,
    PlatformAutomationFlowViewSet,
    PlatformCampaignViewSet,
    PlatformContentViewSet,
    PlatformConversationViewSet,
    PlatformGrowthDashboardAPIView,
    PlatformLeadViewSet,
    OAuthMetaStartAPIView,
    OAuthMetaCallbackAPIView,
)

router = DefaultRouter()
router.register(r"campaigns", PlatformCampaignViewSet, basename="platform-growth-campaigns")
router.register(r"content", PlatformContentViewSet, basename="platform-growth-content")
router.register(r"leads", PlatformLeadViewSet, basename="platform-growth-leads")
router.register(r"conversations", PlatformConversationViewSet, basename="platform-growth-conversations")
router.register(r"flows", PlatformAutomationFlowViewSet, basename="platform-growth-flows")

router.register(r"growth/channels", GrowthChannelConnectionViewSet, basename="platform-growth-channels")
router.register(r"growth/oauth-states", GrowthOAuthStateViewSet, basename="platform-growth-oauth-states")
router.register(r"growth/oauth-tokens", GrowthOAuthTokenViewSet, basename="platform-growth-oauth-tokens")
router.register(r"growth/drafts", GrowthContentDraftViewSet, basename="platform-growth-drafts")
router.register(r"growth/queue", GrowthContentQueueItemViewSet, basename="platform-growth-queue")
router.register(r"growth/recipes", GrowthAutomationRecipeViewSet, basename="platform-growth-recipes")
router.register(r"growth/scheduled-jobs", GrowthScheduledPostJobViewSet, basename="platform-growth-scheduled-jobs")

urlpatterns = [
    path("dashboard/", PlatformGrowthDashboardAPIView.as_view(), name="platform-growth-dashboard"),
    path("growth/oauth/meta/start/", OAuthMetaStartAPIView.as_view(), name="platform-growth-meta-oauth-start"),
    path("growth/oauth/meta/callback/", OAuthMetaCallbackAPIView.as_view(), name="platform-growth-meta-oauth-callback"),
    path("meta/webhook/", MetaWebhookEventAPIView.as_view(), name="platform-growth-meta-webhook"),
    path("meta/webhook/verify/", MetaWebhookVerificationAPIView.as_view(), name="platform-growth-meta-webhook-verify"),
    path("", include(router.urls)),
]
