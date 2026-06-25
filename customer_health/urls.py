from __future__ import annotations

from django.urls import path

from .views import (
    CustomerHealthMeView,
    NutritionAnalyzeView,
    RedeemHealthAccessCodeView,
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
]
