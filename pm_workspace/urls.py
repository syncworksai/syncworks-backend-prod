from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .advanced_billing_views import advanced_tenant_billing, collections_statement_preview, generate_advanced_late_fees
from .billing_policy_views import apply_company_billing_template, company_billing_template, rent_allocation
from .billing_views import generate_tenant_charges, my_tenant_account, portfolio_billing_summary, tenant_billing_profile
from .communication_views import bulk_delete_ledger, investor_ledger, my_conversations, pm_conversations, reply_conversation, request_ledger_information, requester_reply, resolve_conversation
from .deposit_views import apply_deposit, deposit_status
from .dashboard_views import command_center
from .document_builder_views import document_builder_bootstrap, document_builder_finalize, document_builder_prefill, document_builder_save
from .document_views import PMPropertyDocumentViewSet, document_template_catalog, property_document_checklist
from .lead_views import lead_convert_to_tenant, lead_detail, lead_note, lead_reply_email, leads
from .leasing_views import PMDocumentPacketViewSet, PMLedgerEntryViewSet, PMLeaseViewSet, PMProspectViewSet, PMUnitViewSet
from .ledger_correction_views import correct_ledger_entry, undo_generated_charges
from .owner_views import PMPropertyOwnerViewSet, complete_tenant_onboarding_internally
from .payer_billing_views import generate_installment_late_fees, payer_profile, rebuild_split_rent
from .property_profile_views import property_inventory, property_inventory_item, property_profile
from .record_views import inbox_reply, occupancies, tenant_cases, tenant_portal_communications, unified_inbox, update_tenant_case
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
    path("dashboard/command-center/", command_center),
    path("tenants/<int:tenant_id>/complete-internally/", complete_tenant_onboarding_internally),
    path("tenants/<int:tenant_id>/complete-internally", complete_tenant_onboarding_internally),
    path("tenants/<int:tenant_id>/complete_internal/", complete_tenant_onboarding_internally),
    path("tenants/<int:tenant_id>/correct-profile/", correct_tenant_profile),
    path("properties/<int:property_id>/profile/", property_profile),
    path("properties/<int:property_id>/inventory/", property_inventory),
    path("properties/<int:property_id>/inventory/<int:item_id>/", property_inventory_item),
    path("occupancies/", occupancies),
    path("occupancies/<int:occupancy_id>/move-out/", close_occupancy_workflow),
    path("occupancies/<int:occupancy_id>/evict/", evict_occupancy),
    path("tenant-cases/", tenant_cases),
    path("tenant-cases/<int:case_id>/", update_tenant_case),
    path("messages/", unified_inbox),
    path("messages/<int:conversation_id>/reply/", inbox_reply),
    path("messages/<int:conversation_id>/email/", email_conversation),
    path("leads/", leads),
    path("leads/<int:lead_id>/", lead_detail),
    path("leads/<int:lead_id>/note/", lead_note),
    path("leads/<int:lead_id>/reply-email/", lead_reply_email),
    path("leads/<int:lead_id>/convert-to-tenant/", lead_convert_to_tenant),
    path("make-ready/", make_ready_board),
    path("make-ready/<int:work_order_id>/", update_make_ready),
    path("tenant-portal/communications/", tenant_portal_communications),
    path("billing/summary/", portfolio_billing_summary),
    path("billing/company-template/", company_billing_template),
    path("billing/tenants/<int:tenant_id>/apply-company-template/", apply_company_billing_template),
    path("billing/tenants/<int:tenant_id>/rent-allocation/", rent_allocation),
    path("billing/tenants/<int:tenant_id>/", tenant_billing_profile),
    path("billing/tenants/<int:tenant_id>/advanced/", advanced_tenant_billing),
    path("billing/tenants/<int:tenant_id>/payer-profile/", payer_profile),
    path("billing/tenants/<int:tenant_id>/deposit-status/", deposit_status),
    path("billing/tenants/<int:tenant_id>/apply-deposit/", apply_deposit),
    path("billing/tenants/<int:tenant_id>/rebuild-split-rent/", rebuild_split_rent),
    path("billing/tenants/<int:tenant_id>/generate-installment-late-fees/", generate_installment_late_fees),
    path("billing/tenants/<int:tenant_id>/generate/", generate_tenant_charges),
    path("billing/tenants/<int:tenant_id>/generate-advanced-late-fees/", generate_advanced_late_fees),
    path("billing/tenants/<int:tenant_id>/collections-preview/", collections_statement_preview),
    path("billing/tenants/<int:tenant_id>/undo-generated/", undo_generated_charges),
    path("billing/my-account/", my_tenant_account),
    path("billing/investor-ledger/", investor_ledger),
    path("ledger-entries/", legacy_ledger_list),
    path("ledger/bulk-delete/", bulk_delete_ledger),
    path("ledger/<int:entry_id>/correct/", correct_ledger_entry),
    path("ledger/<int:entry_id>/request-information/", request_ledger_information),
    path("document-library/checklist/", property_document_checklist),
    path("document-library/templates/", document_template_catalog),
    path("document-builder/properties/<int:property_id>/", document_builder_bootstrap),
    path("document-builder/properties/<int:property_id>/templates/<str:template_id>/prefill/", document_builder_prefill),
    path("document-builder/properties/<int:property_id>/save/", document_builder_save),
    path("document-builder/packets/<int:packet_id>/finalize/", document_builder_finalize),
    path("conversations/", pm_conversations),
    path("conversations/<int:conversation_id>/reply/", reply_conversation),
    path("conversations/<int:conversation_id>/resolve/", resolve_conversation),
    path("conversations/mine/", my_conversations),
    path("conversations/<int:conversation_id>/requester-reply/", requester_reply),
    path("", include(router.urls)),
]
