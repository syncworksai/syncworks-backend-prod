from django.urls import include, path
from rest_framework.routers import DefaultRouter

from platform_growth.views import (
    MetaWebhookEventAPIView,
    MetaWebhookVerificationAPIView,
    PlatformAutomationFlowViewSet,
    PlatformCampaignViewSet,
    PlatformContentViewSet,
    PlatformConversationViewSet,
    PlatformGrowthDashboardAPIView,
    PlatformLeadViewSet,
)

router = DefaultRouter()
router.register(r"campaigns", PlatformCampaignViewSet, basename="platform-growth-campaigns")
router.register(r"content", PlatformContentViewSet, basename="platform-growth-content")
router.register(r"leads", PlatformLeadViewSet, basename="platform-growth-leads")
router.register(r"conversations", PlatformConversationViewSet, basename="platform-growth-conversations")
router.register(r"flows", PlatformAutomationFlowViewSet, basename="platform-growth-flows")

urlpatterns = [
    path("dashboard/", PlatformGrowthDashboardAPIView.as_view(), name="platform-growth-dashboard"),
    path("meta/webhook/", MetaWebhookEventAPIView.as_view(), name="platform-growth-meta-webhook"),
    path("meta/webhook/verify/", MetaWebhookVerificationAPIView.as_view(), name="platform-growth-meta-webhook-verify"),
    path("", include(router.urls)),
]
