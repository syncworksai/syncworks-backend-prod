from django.urls import path
from .views import BusinessFeaturesView, BusinessFeatureTrialView, FounderFeatureOverrideView, FounderStripePriceAuditView
urlpatterns = [
    path("god/pricing/verify/", FounderStripePriceAuditView.as_view()),
    path("businesses/<int:pk>/", BusinessFeaturesView.as_view()),
    path("businesses/<int:pk>/trial/", BusinessFeatureTrialView.as_view()),
    path("god/businesses/<int:pk>/override/", FounderFeatureOverrideView.as_view()),
]
