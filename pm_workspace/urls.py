from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .leasing_views import PMDocumentPacketViewSet, PMLedgerEntryViewSet, PMLeaseViewSet, PMProspectViewSet, PMUnitViewSet
from .owner_views import PMPropertyOwnerViewSet, complete_tenant_onboarding_internally
from .views import PMProjectViewSet, PMPropertyViewSet, PMTenantInvitationViewSet, PMTenantViewSet, PMWorkspaceViewSet
from .workorder_views import PMWorkOrderViewSet

router = DefaultRouter()
router.register(r"workspaces", PMWorkspaceViewSet, basename="pm-workspaces")
router.register(r"properties", PMPropertyViewSet, basename="pm-properties")
router.register(r"property-owners", PMPropertyOwnerViewSet, basename="pm-property-owners")
router.register(r"projects", PMProjectViewSet, basename="pm-projects")
router.register(r"tenants", PMTenantViewSet, basename="pm-tenants")
router.register(r"tenant-invitations", PMTenantInvitationViewSet, basename="pm-tenant-invitations")
router.register(r"units", PMUnitViewSet, basename="pm-units")
router.register(r"prospects", PMProspectViewSet, basename="pm-prospects")
router.register(r"leases", PMLeaseViewSet, basename="pm-leases")
router.register(r"document-packets", PMDocumentPacketViewSet, basename="pm-document-packets")
router.register(r"ledger", PMLedgerEntryViewSet, basename="pm-ledger")
router.register(r"work-orders", PMWorkOrderViewSet, basename="pm-work-orders")

urlpatterns = [
    path("tenants/<int:tenant_id>/complete-internally/", complete_tenant_onboarding_internally, name="pm-tenant-complete-internally"),
    path("", include(router.urls)),
]
