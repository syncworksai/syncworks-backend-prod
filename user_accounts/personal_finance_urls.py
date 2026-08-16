from django.urls import include, path
from rest_framework.routers import DefaultRouter

from user_accounts.viewsets.finance_automation import FinanceAutomationViewSet
from user_accounts.viewsets.personal_finance import (
    FinanceAccountViewSet,
    FinanceBudgetViewSet,
    FinanceConnectionViewSet,
    FinanceDashboardViewSet,
    FinanceGoalViewSet,
    FinanceLiabilityViewSet,
    FinanceObligationViewSet,
    FinanceTransactionViewSet,
)

router = DefaultRouter()
router.register(r"connections", FinanceConnectionViewSet, basename="finance-connections")
router.register(r"accounts", FinanceAccountViewSet, basename="finance-accounts")
router.register(r"liabilities", FinanceLiabilityViewSet, basename="finance-liabilities")
router.register(r"obligations", FinanceObligationViewSet, basename="finance-obligations")
router.register(r"transactions", FinanceTransactionViewSet, basename="finance-transactions")
router.register(r"goals", FinanceGoalViewSet, basename="finance-goals")
router.register(r"budgets", FinanceBudgetViewSet, basename="finance-budgets")
router.register(r"dashboard", FinanceDashboardViewSet, basename="finance-dashboard")
router.register(r"automation", FinanceAutomationViewSet, basename="finance-automation")

urlpatterns = [path("", include(router.urls))]
