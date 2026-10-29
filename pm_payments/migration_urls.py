from django.urls import path
from .migration_views import PaymentMigrationPlanAPIView, PaymentMigrationFounderReviewAPIView

urlpatterns = [
    path("plan/", PaymentMigrationPlanAPIView.as_view(), name="payment-migration-plan"),
    path("review-test/", PaymentMigrationFounderReviewAPIView.as_view(), name="payment-migration-founder-review"),
]
