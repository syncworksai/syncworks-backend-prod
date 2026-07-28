from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PMPropertyViewSet, PMTenantInvitationViewSet, PMTenantViewSet, PMWorkspaceViewSet

router = DefaultRouter()
router.register(r"workspaces", PMWorkspaceViewSet, basename="pm-workspaces")
router.register(r"properties", PMPropertyViewSet, basename="pm-properties")
router.register(r"tenants", PMTenantViewSet, basename="pm-tenants")
router.register(r"tenant-invitations", PMTenantInvitationViewSet, basename="pm-tenant-invitations")

urlpatterns = [path("", include(router.urls))]
