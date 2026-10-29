from django.urls import path
from .views import PMCollectionSetupAPIView

urlpatterns = [
    path("setup/", PMCollectionSetupAPIView.as_view(), name="pm-payment-collection-setup"),
]
