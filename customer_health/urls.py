from __future__ import annotations

from django.urls import path

from .views import (
    CustomerHealthMeView,
    NutritionAnalyzeView,
    RedeemHealthAccessCodeView,
)
from .voice_views import (
    HealthVoiceOptionsView,
    HealthVoiceSpeakView,
)

app_name = "customer_health"

urlpatterns = [
    path(
        "me/",
        CustomerHealthMeView.as_view(),
        name="me",
    ),
    path(
        "redeem-access-code/",
        RedeemHealthAccessCodeView.as_view(),
        name="redeem-access-code",
    ),
    path(
        "nutrition/analyze/",
        NutritionAnalyzeView.as_view(),
        name="nutrition-analyze",
    ),
    path(
        "voice/options/",
        HealthVoiceOptionsView.as_view(),
        name="voice-options",
    ),
    path(
        "voice/speak/",
        HealthVoiceSpeakView.as_view(),
        name="voice-speak",
    ),
]
