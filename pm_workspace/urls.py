from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .advanced_billing_views import advanced_tenant_billing, collections_statement_preview, generate_advanced_late_fees
from .billing_views import generate_tenant_charges, my_tenant_account, portfolio_billing_summary, tenant_billing_profile
from .communication_views import (
    bulk_delete_ledger,
    investor_ledger,
    my_conversations,
    pm_conversations,
    reply_conversation,
    request_ledger_information,
    requester_reply,
    resolve_conversation,
)
from .document_builder_views import document_builder_bootstrap, document_builder_finalize, document_builder_prefill, document_builder_save
from .document_views import PMPropertyDocumentViewSet, document_template_catalog, property_document_checklist
from .leasing_views import PMDocumentPacketViewSet, PMLedgerEntryViewSet, PMLeaseViewSet, PMProspectViewSet, PMUnitViewSet
from .ledger_correction_views import correct_ledger_entry, undo_generated_charges
from .owner_views import PMPropertyOwnerViewSet, complete_tenant_onboarding_internally
from .property_profile_views import property_inventory, property_inventory_item, property_profile
from .record_views import (
    inbox_reply,
    occupancies,
    tenant_cases,
    tenant_portal_communications,
    unified_inbox,
    update_tenant_case,
)
from .tenant_profile_views import correct_tenant_profile
from .views import PMProjectViewSet, PMPropertyViewSet, PMTenantInvitationViewSet, PMTenantViewSet, PMWorkspaceViewSet
from .workflow_close_views import close_occupancy_workflow
from .workflow_views import email_conversation, evict_occupancy, make_ready_board, update_make_ready
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
router.register(r"property-documents", PMPropertyDocumentViewSet, basename="pm-property-documents")
router.register(r"ledger", PMLedgerEntryViewSet, basename="pm-ledger")
router.register(r"work-orders", PMWorkOrderViewSet, basename="pm-work-orders")

legacy_ledger_list = PMLedgerEntryViewSet.as_view({"get": "list", "post": "create"})

urlpatterns = [
    path("tenants/<int:tenant_id>/complete-internally/", complete_tenant_onboarding_internally, name="pm-tenant-complete-internally"),
    path("tenants/<int:tenant_id>/complete-internally", complete_tenant_onboarding_internally, name="pm-tenant-complete-internally-no-slash"),
    path("tenants/<int:tenant_id>/complete_internal/", complete_tenant_onboarding_internally, name="pm-tenant-complete-internal-compat"),
    path("tenants/<int:tenant_id>/correct-profile/", correct_tenant_profile, name="pm-tenant-correct-profile"),
    path("properties/<int:property_id>/profile/", property_profile, name="pm-property-detail-profile"),
    path("properties/<int:property_id>/inventory/", property_inventory, name="pm-property-inventory"),
    path("properties/<int:property_id>/inventory/<int:item_id>/", property_inventory_item, name="pm-property-inventory-item"),
    path("occupancies/", occupancies, name="pm-occupancies"),
    path("occupancies/<int:occupancy_id>/move-out/", close_occupancy_workflow, name="pm-occupancy-move-out"),
    path("occupancies/<int:occupancy_id>/evict/", evict_occupancy, name="pm-occupancy-evict"),
    path("tenant-cases/", tenant_cases, name="pm-tenant-cases"),
    path("tenant-cases/<int:case_id>/", update_tenant_case, name="pm-tenant-case-update"),
    path("messages/", unified_inbox, name="pm-unified-inbox"),
    path("messages/<int:conversation_id>/reply/", inbox_reply, name="pm-unified-inbox-reply"),
    path("messages/<int:conversation_id>/email/", email_conversation, name="pm-unified-inbox-email"),
    path("make-ready/", make_ready_board, name="pm-make-ready-board"),
    path("make-ready/<int:work_order_id>/", update_make_ready, name="pm-make-ready-update"),
    path("tenant-portal/communications/", tenant_portal_communications, name="pm-tenant-portal-communications"),
    path("billing/summary/", portfolio_billing_summary, name="pm-billing-summary"),
    path("billing/tenants/<int:tenant_id>/", tenant_billing_profile, name="pm-tenant-billing-profile"),
    path("billing/tenants/<int:tenant_id>/advanced/", advanced_tenant_billing, name="pm-tenant-advanced-billing"),
    path("billing/tenants/<int:tenant_id>/generate/", generate_tenant_charges, name="pm-tenant-billing-generate"),
    path("billing/tenants/<int:tenant_id>/generate-advanced-late-fees/", generate_advanced_late_fees, name="pm-tenant-generate-advanced-late-fees"),
    path("billing/tenants/<int:tenant_id>/collections-preview/", collections_statement_preview, name="pm-tenant-collections-preview"),
    path("billing/tenants/<int:tenant_id>/undo-generated/", undo_generated_charges, name="pm-tenant-billing-undo-generated"),
    path("billing/my-account/", my_tenant_account, name="pm-tenant-my-account"),
    path("billing/investor-ledger/", investor_ledger, name="pm-investor-ledger"),
    path("ledger-entries/", legacy_ledger_list, name="pm-ledger-entries-compat"),
    path("ledger/bulk-delete/", bulk_delete_ledger, name="pm-ledger-bulk-delete"),
    path("ledger/<int:entry_id>/correct/", correct_ledger_entry, name="pm-ledger-correct-entry"),
    path("ledger/<int:entry_id>/request-information/", request_ledger_information, name="pm-ledger-request-information"),
    path("document-library/checklist/", property_document_checklist, name="pm-document-checklist"),
    path("document-library/templates/", document_template_catalog, name="pm-document-template-catalog"),
    path("document-builder/properties/<int:property_id>/", document_builder_bootstrap, name="pm-document-builder-bootstrap"),
    path("document-builder/properties/<int:property_id>/templates/<str:template_id>/prefill/", document_builder_prefill, name="pm-document-builder-prefill"),
    path("document-builder/properties/<int:property_id>/save/", document_builder_save, name="pm-document-builder-save"),
    path("document-builder/packets/<int:packet_id>/finalize/", document_builder_finalize, name="pm-document-builder-finalize"),
    path("conversations/", pm_conversations, name="pm-conversations"),
    path("conversations/<int:conversation_id>/reply/", reply_conversation, name="pm-conversation-reply"),
    path("conversations/<int:conversation_id>/resolve/", resolve_conversation, name="pm-conversation-resolve"),
    path("conversations/mine/", my_conversations, name="pm-my-conversations"),
    path("conversations/<int:conversation_id>/requester-reply/", requester_reply, name="pm-conversation-requester-reply"),
    path("", include(router.urls)),
]
