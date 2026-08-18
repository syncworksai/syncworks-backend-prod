# platform_growth/urls.py
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from platform_growth.business_lead_views import PlatformConversationViewSet, PlatformLeadViewSet
from platform_growth.connection_views import EasyOAuthMetaCallbackAPIView, EasyOAuthMetaStartAPIView
from platform_growth.intelligence_views import GrowthIntelligenceAPIView
from platform_growth.runtime_views import GrowthRuntimeAPIView
from platform_growth.story_views import GrowthStoryDraftAPIView
from platform_growth.webhook_views import MetaWebhookEventAPIView
from platform_growth.views import (
    GrowthAutomationRecipeViewSet,
    GrowthChannelConnectionViewSet,
    GrowthContentDraftViewSet,
    GrowthContentQueueItemViewSet,
    GrowthOAuthStateViewSet,
    GrowthOAuthTokenViewSet,
    GrowthScheduledPostJobViewSet,
    MetaWebhookVerificationAPIView,
    PlatformAutomationFlowViewSet,
    PlatformCampaignViewSet,
    PlatformContentViewSet,
    PlatformGrowthDashboardAPIView,
    PlatformAutomationRuleViewSet,
    PlatformAutomationExecutionViewSet,
)

router = DefaultRouter()
router.register(r"campaigns", PlatformCampaignViewSet, basename="platform-growth-campaigns")
router.register(r"content", PlatformContentViewSet, basename="platform-growth-content")
router.register(r"leads", PlatformLeadViewSet, basename="platform-growth-leads")
router.register(r"conversations", PlatformConversationViewSet, basename="platform-growth-conversations")
router.register(r"flows", PlatformAutomationFlowViewSet, basename="platform-growth-flows")
router.register(r"automation-rules", PlatformAutomationRuleViewSet, basename="platform-growth-automation-rules")
router.register(r"automation-executions", PlatformAutomationExecutionViewSet, basename="platform-growth-automation-executions")

router.register(r"growth/channels", GrowthChannelConnectionViewSet, basename="platform-growth-channels")
router.register(r"growth/oauth-states", GrowthOAuthStateViewSet, basename="platform-growth-oauth-states")
router.register(r"growth/oauth-tokens", GrowthOAuthTokenViewSet, basename="platform-growth-oauth-tokens")
router.register(r"growth/drafts", GrowthContentDraftViewSet, basename="platform-growth-drafts")
router.register(r"growth/queue", GrowthContentQueueItemViewSet, basename="platform-growth-queue")
router.register(r"growth/recipes", GrowthAutomationRecipeViewSet, basename="platform-growth-recipes")
router.register(r"growth/scheduled-jobs", GrowthScheduledPostJobViewSet, basename="platform-growth-scheduled-jobs")

urlpatterns = [
    path("dashboard/", PlatformGrowthDashboardAPIView.as_view(), name="platform-growth-dashboard"),
    path("growth/intelligence/", GrowthIntelligenceAPIView.as_view(), name="platform-growth-intelligence"),
    path("growth/story-drafts/", GrowthStoryDraftAPIView.as_view(), name="platform-growth-story-drafts"),
    path("growth/oauth/meta/start/", EasyOAuthMetaStartAPIView.as_view(), name="platform-growth-meta-oauth-start"),
    path("growth/oauth/meta/callback/", EasyOAuthMetaCallbackAPIView.as_view(), name="platform-growth-meta-oauth-callback"),
    path("growth/runtime/run/", GrowthRuntimeAPIView.as_view(), name="platform-growth-runtime-run"),
    path("meta/webhook/", MetaWebhookEventAPIView.as_view(), name="platform-growth-meta-webhook"),
    path("meta/webhook/verify/", MetaWebhookVerificationAPIView.as_view(), name="platform-growth-meta-webhook-verify"),
    path("", include(router.urls)),
]
