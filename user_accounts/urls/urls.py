# user_accounts/urls/platform.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from user_accounts.viewsets.platform import (
    PlatformMeAPIView,
    PlatformKpisAPIView,
    PlatformBroadcastAPIView,
    PlatformUsersViewSet,
    PlatformBusinessesViewSet,
    PlatformBillingSummaryViewSet,
    PlatformKpiTimeseriesViewSet,
    PlatformNewsReelAdminViewSet,
)

router = DefaultRouter()
router.register(r"users", PlatformUsersViewSet, basename="platform-users")
router.register(r"businesses", PlatformBusinessesViewSet, basename="platform-businesses")
router.register(r"billing/summary", PlatformBillingSummaryViewSet, basename="platform-billing-summary")
router.register(r"kpis/timeseries", PlatformKpiTimeseriesViewSet, basename="platform-kpis-timeseries")
router.register(r"news-reel", PlatformNewsReelAdminViewSet, basename="platform-news-reel")

urlpatterns = [
    path("me/", PlatformMeAPIView.as_view()),
    path("kpis/", PlatformKpisAPIView.as_view()),
    path("broadcasts/", PlatformBroadcastAPIView.as_view()),
    path("", include(router.urls)),
]
