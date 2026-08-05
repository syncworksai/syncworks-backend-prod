from django.urls import path

from .views import (
    JarvisCheckInView,
    JarvisCheckOutView,
    JarvisCheckoutView,
    JarvisPortalView,
    JarvisProfileView,
    JarvisWebhookView,
)

urlpatterns = [
    path("profile/", JarvisProfileView.as_view(), name="jarvis-profile"),
    path("check-in/", JarvisCheckInView.as_view(), name="jarvis-check-in"),
    path("check-out/", JarvisCheckOutView.as_view(), name="jarvis-check-out"),
    path("billing/checkout/", JarvisCheckoutView.as_view(), name="jarvis-checkout"),
    path("billing/portal/", JarvisPortalView.as_view(), name="jarvis-portal"),
    path("billing/webhook/", JarvisWebhookView.as_view(), name="jarvis-webhook"),
]
