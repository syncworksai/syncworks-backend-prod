from django.urls import path

from .views import (
    CashForecastAPIView, ExpenseDetailAPIView, ExpenseListCreateAPIView,
    FinanceSettingsAPIView, FinanceSummaryAPIView, ForecastItemDetailAPIView,
    ForecastItemListCreateAPIView, JobCostReviewAPIView, JobProfitAPIView,
)

urlpatterns = [
    path("expenses/", ExpenseListCreateAPIView.as_view(), name="business-finance-expenses"),
    path("expenses/<int:expense_id>/", ExpenseDetailAPIView.as_view(), name="business-finance-expense-detail"),
    path("forecast-items/", ForecastItemListCreateAPIView.as_view(), name="business-finance-forecast-items"),
    path("forecast-items/<int:forecast_id>/", ForecastItemDetailAPIView.as_view(), name="business-finance-forecast-detail"),
    path("settings/", FinanceSettingsAPIView.as_view(), name="business-finance-settings"),
    path("summary/", FinanceSummaryAPIView.as_view(), name="business-finance-summary"),
    path("job-profit/", JobProfitAPIView.as_view(), name="business-finance-jobs"),
    path("jobs/<int:ticket_id>/review/", JobCostReviewAPIView.as_view(), name="business-finance-job-review"),
    path("cash-forecast/", CashForecastAPIView.as_view(), name="business-finance-cash-forecast"),
]
