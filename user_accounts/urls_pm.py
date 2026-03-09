# backend/user_accounts/urls_pm.py
from __future__ import annotations

from rest_framework.routers import DefaultRouter

from user_accounts.viewsets.pm_properties import PMPropertyViewSet
from user_accounts.viewsets.pm_units import PMUnitViewSet
from user_accounts.viewsets.pm_tenants import PMTenantViewSet
from user_accounts.viewsets.pm_invites import PMInviteViewSet

router = DefaultRouter()
router.register(r"pm/properties", PMPropertyViewSet, basename="pm-properties")
router.register(r"pm/units", PMUnitViewSet, basename="pm-units")
router.register(r"pm/tenants", PMTenantViewSet, basename="pm-tenants")
router.register(r"pm/invites", PMInviteViewSet, basename="pm-invites")

urlpatterns = router.urls
