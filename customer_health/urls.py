from __future__ import annotations

from django.urls import path

from .views import CustomerHealthMeView

app_name = "customer_health"

urlpatterns = [
    path("me/", CustomerHealthMeView.as_view(), name="me"),
]