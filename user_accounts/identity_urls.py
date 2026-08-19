from django.urls import path

from user_accounts.views.identity import (
    BusinessTrustAPIView,
    CurrentLocationContextAPIView,
    IdentityLocationDetailAPIView,
    IdentityLocationsAPIView,
    IdentityProfileAPIView,
)

urlpatterns = [
    path("profile/", IdentityProfileAPIView.as_view(), name="identity-profile"),
    path("locations/", IdentityLocationsAPIView.as_view(), name="identity-locations"),
    path("locations/<int:location_id>/", IdentityLocationDetailAPIView.as_view(), name="identity-location-detail"),
    path("current-location/", CurrentLocationContextAPIView.as_view(), name="identity-current-location"),
    path("businesses/<int:business_id>/trust/", BusinessTrustAPIView.as_view(), name="identity-business-trust"),
]
