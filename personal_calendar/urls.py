from django.urls import path
from rest_framework.routers import DefaultRouter

from .connection_views import (
    CalendarConnectionDetailView,
    CalendarConnectionListView,
    CalendarConnectionSyncView,
    CalendarOAuthStartView,
    GoogleCalendarOAuthCallbackView,
    MicrosoftCalendarOAuthCallbackView,
)
from .runtime_views import CalendarRuntimeAPIView
from .views import PersonalCalendarEventViewSet

router = DefaultRouter()
router.register("events", PersonalCalendarEventViewSet, basename="personal-calendar-event")

urlpatterns = [
    path("connections/", CalendarConnectionListView.as_view(), name="calendar-connections"),
    path("connections/oauth/start/", CalendarOAuthStartView.as_view(), name="calendar-oauth-start"),
    path("connections/oauth/google/callback/", GoogleCalendarOAuthCallbackView.as_view(), name="calendar-google-callback"),
    path("connections/oauth/microsoft/callback/", MicrosoftCalendarOAuthCallbackView.as_view(), name="calendar-microsoft-callback"),
    path("connections/<str:connection_id>/", CalendarConnectionDetailView.as_view(), name="calendar-connection-detail"),
    path("connections/<str:connection_id>/sync/", CalendarConnectionSyncView.as_view(), name="calendar-connection-sync"),
    path("runtime/run/", CalendarRuntimeAPIView.as_view(), name="calendar-runtime-run"),
] + router.urls
