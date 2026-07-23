from django.urls import path

from .views import (
    HealthAthleteProfileView,
    HealthPlanControlView,
    HealthSimulationPreferencesView,
)

urlpatterns = [
    path("profile/", HealthAthleteProfileView.as_view(), name="health-athlete-profile"),
    path("plan-control/", HealthPlanControlView.as_view(), name="health-plan-control"),
    path(
        "simulation-preferences/",
        HealthSimulationPreferencesView.as_view(),
        name="health-simulation-preferences",
    ),
]
