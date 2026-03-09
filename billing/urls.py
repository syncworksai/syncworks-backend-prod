# backend/billing/urls.py
from django.urls import path

from . import views
from .stripe_webhook import stripe_webhook

urlpatterns = [
    # your existing endpoints...
    # path("status/", views.billing_status),
    # path("setup-card/", views.setup_card),
    # path("subscription/status/", views.subscription_status),

    # ✅ NEW webhook endpoint
    path("webhook/", stripe_webhook, name="stripe-webhook"),
]
