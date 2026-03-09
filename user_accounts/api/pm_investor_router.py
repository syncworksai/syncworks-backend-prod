# backend/user_accounts/api/pm_investor_router.py
from __future__ import annotations

from rest_framework.routers import DefaultRouter

from user_accounts.viewsets.pm_billing_settings import PMBillingSettingsViewSet
from user_accounts.viewsets.pm_investor_connections import PMInvestorConnectionViewSet
from user_accounts.viewsets.pm_investors import PMInvestorViewSet
from user_accounts.viewsets.investor_portal import InvestorDashboardViewSet

router = DefaultRouter()

# PM-side
router.register(r"pm/investors", PMInvestorViewSet, basename="pm-investors")
router.register(r"pm/investor-connections", PMInvestorConnectionViewSet, basename="pm-investor-connections")
router.register(r"pm/billing-settings", PMBillingSettingsViewSet, basename="pm-billing-settings")

# Investor-side
router.register(r"investor/dashboard", InvestorDashboardViewSet, basename="investor-dashboard")
