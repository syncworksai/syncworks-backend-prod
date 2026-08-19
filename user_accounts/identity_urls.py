from django.urls import path

from user_accounts.views.context_router import ContextLocationRouterAPIView
from user_accounts.views.identity import (
    BusinessTrustAPIView,
    CurrentLocationContextAPIView,
    IdentityLocationDetailAPIView,
    IdentityLocationsAPIView,
    IdentityProfileAPIView,
)
from user_accounts.views.identity_admin import (
    PlatformBusinessTrustAPIView,
    PlatformBusinessVerificationQueueAPIView,
)
from user_accounts.views.location_context import ReverseCurrentLocationAPIView

urlpatterns = [
    path("profile/", IdentityProfileAPIView.as_view(), name="identity-profile"),
    path("locations/", IdentityLocationsAPIView.as_view(), name="identity-locations"),
    path("locations/<int:location_id>/", IdentityLocationDetailAPIView.as_view(), name="identity-location-detail"),
    path("current-location/", CurrentLocationContextAPIView.as_view(), name="identity-current-location"),
    path("current-location/resolve/", ReverseCurrentLocationAPIView.as_view(), name="identity-current-location-resolve"),
    path("context-location/", ContextLocationRouterAPIView.as_view(), name="identity-context-location"),
    path("businesses/<int:business_id>/trust/", BusinessTrustAPIView.as_view(), name="identity-business-trust"),
    path("platform/verifications/", PlatformBusinessVerificationQueueAPIView.as_view(), name="identity-platform-verification-queue"),
    path("platform/businesses/<int:business_id>/trust/", PlatformBusinessTrustAPIView.as_view(), name="identity-platform-business-trust"),
]
