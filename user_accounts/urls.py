from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from user_accounts.viewsets.team import TeamInvitesViewSet, TeamMembersViewSet
from user_accounts.viewsets.me import MeViewSet

from user_accounts.viewsets.auth import (
    LogoutAPIView,
    MeAPIView,
    RegisterAPIView,
    TokenLoginAPIView,
    UpgradeToSboAPIView,
    UpgradeToSboPromoAPIView,
)

from user_accounts.viewsets.platform_billing import (
    BillingPreviewAPIView,
    BillingStatusAPIView,
    CreateOrUpdateMonthlyBillAPIView,
    CreateSetupCheckoutSessionAPIView,
    StripeWebhookAPIView,
    UnlockRequestAPIView,
    UserBillingStatusAPIView,
    CreateUserSetupCheckoutSessionAPIView,
)

from user_accounts.viewsets.subscriptions import (
    CancelSubscriptionAPIView,
    CreateSubscriptionCheckoutSessionAPIView,
    SubscriptionStatusAPIView,
)

from user_accounts.viewsets.platform_admin import PlatformKPIAPIView

from user_accounts.viewsets.notifications import MeNewsReelViewSet, NotificationViewSet
from user_accounts.viewsets.platform_broadcasts import (
    PlatformBroadcastAPIView,
    PlatformNewsReelAdminViewSet,
)

from user_accounts.viewsets.platform_console import (
    PlatformBillingSummaryViewSet,
    PlatformBusinessesViewSet,
    PlatformKpiTimeseriesViewSet,
    PlatformUsersViewSet,
)

from user_accounts.viewsets.platform_metrics import (
    PlatformMetricsSummaryAPIView,
    PlatformMetricsAlertsAPIView,
)

from user_accounts.viewsets.tickets import (
    InvoiceViewSet,
    TicketAttachmentViewSet,
    TicketMessageViewSet,
    TicketQuoteViewSet,
    TicketViewSet,
)

from user_accounts.viewsets.templates import DocumentTemplateViewSet
from user_accounts.viewsets.service_catalog import ServiceCatalogItemViewSet
from user_accounts.viewsets.categories import ServiceCategoryViewSet
from user_accounts.viewsets.marketplace import ServiceRequestViewSet
from user_accounts.viewsets.bootstrap import BootstrapMyBusinessAPIView

from user_accounts.viewsets.business import (
    BusinessMemberViewSet,
    BusinessViewSet,
    BusinessTeamViewSet,
    EmployeeInviteAcceptViewSet,
)
from user_accounts.viewsets.me_businesses import MeBusinessesViewSet

from user_accounts.viewsets.promo import PromoCodeViewSet, PromoRedemptionViewSet
from user_accounts.viewsets.customer_settings import CustomerSettingsViewSet
from user_accounts.viewsets.communication_preferences import CurrentCommunicationPreferenceAPIView
from user_accounts.viewsets.automation import (
    AutomationExecuteAPIView,
    AutomationExecutionListAPIView,
    AutomationRuleDetailAPIView,
    AutomationRuleListCreateAPIView,
)
from user_accounts.viewsets.operations import (
    EventAlertCreateAPIView,
    OperationalAlertDetailAPIView,
    OperationalAlertListAPIView,
    TicketETAAPIView,
    TicketEventListCreateAPIView,
)
from user_accounts.viewsets.inventory import (
    InventoryItemListCreateAPIView,
    InventoryLocationListCreateAPIView,
    InventoryStockListAPIView,
    PurchaseOrderLineCreateAPIView,
    PurchaseOrderListCreateAPIView,
    PurchaseReceiptCreateAPIView,
    StockMovementCreateAPIView,
    VendorListCreateAPIView,
)
from user_accounts.viewsets.workflow import (
    BusinessPriorityQueueAPIView,
    TicketDependencyListCreateAPIView,
    TicketNextActionAPIView,
    TicketRequirementDetailAPIView,
    TicketRequirementListCreateAPIView,
)
from user_accounts.viewsets.resources import (
    ResourceAssignmentDetailAPIView,
    ResourceDetailAPIView,
    ResourceListCreateAPIView,
    ResourceMovementAPIView,
    TicketResourceAssignmentAPIView,
)
from user_accounts.viewsets.assets import (
    AssetDetailAPIView,
    AssetIdentifierCreateAPIView,
    AssetListCreateAPIView,
    AssetScanResolveAPIView,
    TicketAssetLinkAPIView,
)
from user_accounts.viewsets.ticket_conversations import (
    TicketConversationControlsAPIView,
    TicketConversationListAPIView,
    TicketConversationMessagesAPIView,
)
from user_accounts.viewsets.favorites import MeFavoriteBusinessViewSet

from user_accounts.viewsets.stripe_connect import (
    StripeConnectExpressStartAPIView,
    StripeConnectExpressStatusAPIView,
)

from user_accounts.viewsets.invoice_checkout import (
    CreateInvoiceCheckoutSessionAPIView,
    InvoicePaymentWebhookAPIView,
)

from user_accounts.viewsets.support_requests import (
    PlatformSupportRequestViewSet,
    SupportRequestViewSet,
)

from user_accounts.viewsets.pm_properties import PMPropertyViewSet
from user_accounts.viewsets.pm_units import PMUnitViewSet
from user_accounts.viewsets.pm_tenants import PMTenantViewSet
from user_accounts.viewsets.pm_invites import PMInviteViewSet
from user_accounts.viewsets.pm_documents import PMDocumentViewSet

from user_accounts.viewsets.pm_employees import PMEmployeeViewSet, PMEmployeeInviteViewSet
from user_accounts.viewsets.pm_section8 import PMSection8CaseViewSet
from user_accounts.viewsets.pm_overview_summary import PMOverviewSummaryAPIView

from user_accounts.viewsets.pm_rent import (
    PMBillingSettingsViewSet,
    PMRentChargeViewSet,
    PMRentPaymentViewSet,
)

from user_accounts.viewsets.pm_rent_webhook import PMRentWebhookAPIView

from user_accounts.viewsets.tenant_portal import (
    TenantSummaryViewSet,
    TenantRentChargeViewSet,
)

from user_accounts.viewsets.tenant_invites import TenantInviteAcceptAPIView

from user_accounts.viewsets.pm_investors import PMInvestorViewSet
from user_accounts.viewsets.pm_investor_connections import PMInvestorConnectionViewSet
from user_accounts.viewsets.investor_portal import InvestorDashboardViewSet

from user_accounts.viewsets.pm_inbox import PMInboxThreadViewSet
from user_accounts.viewsets.investor_claim import InvestorClaimAPIView
from user_accounts.viewsets.investor_inbox import InvestorInboxThreadViewSet

from user_accounts.viewsets.pm_workorders import PMWorkOrderViewSet
from user_accounts.viewsets.ticket_metrics import TicketZipMetricsAPIView

from user_accounts.viewsets.sales_os import (
    SalesPipelineViewSet,
    SalesPipelineMemberViewSet,
    ProspectStageViewSet,
    ProspectViewSet,
    SalesEventViewSet,
    SalesKPIViewSet,
)

from user_accounts.viewsets.cash_fee_invoices import CashFeeInvoiceViewSet
from user_accounts.viewsets.platform_locking import PlatformLockingViewSet
from user_accounts.viewsets.me_business_cards import MeBusinessCardResolveAPIView


ProspectAttachmentViewSet = None
ProspectActivityViewSet = None

try:
    from user_accounts.viewsets.sales_os import ProspectAttachmentViewSet as _ProspectAttachmentViewSet  # type: ignore
    ProspectAttachmentViewSet = _ProspectAttachmentViewSet
except Exception:
    ProspectAttachmentViewSet = None

try:
    from user_accounts.viewsets.sales_os import ProspectActivityViewSet as _ProspectActivityViewSet  # type: ignore
    ProspectActivityViewSet = _ProspectActivityViewSet
except Exception:
    ProspectActivityViewSet = None


router = DefaultRouter()

# ----------------------------
# Core: Team + Me
# ----------------------------
router.register(r"team/members", TeamMembersViewSet, basename="team-members")
router.register(r"team/invites", TeamInvitesViewSet, basename="team-invites")
router.register(r"me", MeViewSet, basename="me")

router.register(r"customer-settings", CustomerSettingsViewSet, basename="customer-settings")
router.register(r"me/favorites/businesses", MeFavoriteBusinessViewSet, basename="me-favorite-businesses")

router.register(r"me/notifications", NotificationViewSet, basename="me-notifications")
router.register(r"me/news-reel", MeNewsReelViewSet, basename="me-news-reel")
router.register(r"notifications", NotificationViewSet, basename="notifications")

router.register(r"businesses", BusinessViewSet, basename="businesses")
router.register(r"business-members", BusinessMemberViewSet, basename="business-members")
router.register(r"me/businesses", MeBusinessesViewSet, basename="me-businesses")

# ----------------------------
# Service Categories / Marketplace
# ----------------------------
router.register(r"service-categories", ServiceCategoryViewSet, basename="service-categories")
router.register(r"service-requests", ServiceRequestViewSet, basename="service-requests")
router.register(r"service-catalog", ServiceCatalogItemViewSet, basename="service-catalog")

router.register(r"tickets", TicketViewSet, basename="tickets")
router.register(r"ticket-messages", TicketMessageViewSet, basename="ticket-messages")
router.register(r"ticket-attachments", TicketAttachmentViewSet, basename="ticket-attachments")
router.register(r"ticket-quotes", TicketQuoteViewSet, basename="ticket-quotes")
router.register(r"invoices", InvoiceViewSet, basename="invoices")

router.register(r"doc-templates", DocumentTemplateViewSet, basename="doc-templates")
router.register(r"cash-fee-invoices", CashFeeInvoiceViewSet, basename="cash-fee-invoices")

# ----------------------------
# User Support
# ----------------------------
router.register(r"support/requests", SupportRequestViewSet, basename="support-requests")

# ----------------------------
# Platform / God Mode
# ----------------------------
router.register(r"platform/news-reel", PlatformNewsReelAdminViewSet, basename="platform-news-reel")
router.register(r"platform/users", PlatformUsersViewSet, basename="platform-users")
router.register(r"platform/businesses", PlatformBusinessesViewSet, basename="platform-businesses")
router.register(r"platform/billing/summary", PlatformBillingSummaryViewSet, basename="platform-billing-summary")
router.register(r"platform/kpis/timeseries", PlatformKpiTimeseriesViewSet, basename="platform-kpis-timeseries")
router.register(r"platform/support/requests", PlatformSupportRequestViewSet, basename="platform-support-requests")
router.register(r"platform/promos", PromoCodeViewSet, basename="platform-promos")
router.register(r"platform/promo-redemptions", PromoRedemptionViewSet, basename="platform-promo-redemptions")
router.register(r"platform/locking", PlatformLockingViewSet, basename="platform-locking")

# ----------------------------
# Property Management
# ----------------------------
router.register(r"pm/properties", PMPropertyViewSet, basename="pm-properties")
router.register(r"pm/units", PMUnitViewSet, basename="pm-units")
router.register(r"pm/tenants", PMTenantViewSet, basename="pm-tenants")
router.register(r"pm/invites", PMInviteViewSet, basename="pm-invites")
router.register(r"pm/documents", PMDocumentViewSet, basename="pm-documents")
router.register(r"pm/employees", PMEmployeeViewSet, basename="pm-employees")
router.register(r"pm/workorders", PMWorkOrderViewSet, basename="pm-workorders")
router.register(r"pm/rent/charges", PMRentChargeViewSet, basename="pm-rent-charges")
router.register(r"pm/rent/payments", PMRentPaymentViewSet, basename="pm-rent-payments")
router.register(r"pm/settings/billing", PMBillingSettingsViewSet, basename="pm-billing-settings")
router.register(r"pm/section8/cases", PMSection8CaseViewSet, basename="pm-section8-cases")

# Tenant Portal (NO X-Business-Id required)
router.register(r"tenant/summary", TenantSummaryViewSet, basename="tenant-summary")
router.register(r"tenant/rent/charges", TenantRentChargeViewSet, basename="tenant-rent-charges")

# Investor
router.register(r"pm/investors", PMInvestorViewSet, basename="pm-investors")
router.register(r"pm/investor-connections", PMInvestorConnectionViewSet, basename="pm-investor-connections")
router.register(r"investor/dashboard", InvestorDashboardViewSet, basename="investor-dashboard")

# ----------------------------
# SALES OS
# ----------------------------
router.register(r"sales/pipelines", SalesPipelineViewSet, basename="sales-pipelines")
router.register(r"sales/members", SalesPipelineMemberViewSet, basename="sales-members")
router.register(r"sales/stages", ProspectStageViewSet, basename="sales-stages")
router.register(r"sales/prospects", ProspectViewSet, basename="sales-prospects")
router.register(r"sales/events", SalesEventViewSet, basename="sales-events")
router.register(r"sales/kpis", SalesKPIViewSet, basename="sales-kpis")

if ProspectAttachmentViewSet is not None:
    router.register(r"sales/prospect-attachments", ProspectAttachmentViewSet, basename="sales-prospect-attachments")

if ProspectActivityViewSet is not None:
    router.register(r"sales/activities", ProspectActivityViewSet, basename="sales-activities")


salesos_stage_list = ProspectStageViewSet.as_view({"get": "list", "post": "create"})
salesos_stage_detail = ProspectStageViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"})

salesos_prospect_list = ProspectViewSet.as_view({"get": "list", "post": "create"})
salesos_prospect_detail = ProspectViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"})

salesos_pipeline_list = SalesPipelineViewSet.as_view({"get": "list", "post": "create"})
salesos_pipeline_detail = SalesPipelineViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"})


urlpatterns = [
    path("automation/rules/", AutomationRuleListCreateAPIView.as_view(), name="automation-rules"),
    path("automation/rules/<int:rule_id>/", AutomationRuleDetailAPIView.as_view(), name="automation-rule-detail"),
    path("automation/rules/<int:rule_id>/execute/", AutomationExecuteAPIView.as_view(), name="automation-rule-execute"),
    path("automation/executions/", AutomationExecutionListAPIView.as_view(), name="automation-executions"),
    path("tickets/<int:ticket_id>/eta/", TicketETAAPIView.as_view(), name="ticket-eta"),
    path("tickets/<int:ticket_id>/operational-events/", TicketEventListCreateAPIView.as_view(), name="ticket-operational-events"),
    path("operations/events/<int:event_id>/alerts/", EventAlertCreateAPIView.as_view(), name="operational-event-alerts"),
    path("operations/alerts/", OperationalAlertListAPIView.as_view(), name="operational-alerts"),
    path("operations/alerts/<int:alert_id>/", OperationalAlertDetailAPIView.as_view(), name="operational-alert-detail"),
    path("inventory/locations/", InventoryLocationListCreateAPIView.as_view(), name="inventory-locations"),
    path("inventory/vendors/", VendorListCreateAPIView.as_view(), name="inventory-vendors"),
    path("inventory/items/", InventoryItemListCreateAPIView.as_view(), name="inventory-items"),
    path("inventory/stock/", InventoryStockListAPIView.as_view(), name="inventory-stock"),
    path("inventory/movements/", StockMovementCreateAPIView.as_view(), name="inventory-movements"),
    path("purchase-orders/", PurchaseOrderListCreateAPIView.as_view(), name="purchase-orders"),
    path("purchase-orders/<int:po_id>/lines/", PurchaseOrderLineCreateAPIView.as_view(), name="purchase-order-lines"),
    path("purchase-orders/<int:po_id>/receipts/", PurchaseReceiptCreateAPIView.as_view(), name="purchase-order-receipts"),
    path("workflow/priority-queue/", BusinessPriorityQueueAPIView.as_view(), name="workflow-priority-queue"),
    path("tickets/<int:ticket_id>/requirements/", TicketRequirementListCreateAPIView.as_view(), name="ticket-requirements"),
    path("requirements/<int:requirement_id>/", TicketRequirementDetailAPIView.as_view(), name="ticket-requirement-detail"),
    path("tickets/<int:ticket_id>/dependencies/", TicketDependencyListCreateAPIView.as_view(), name="ticket-dependencies"),
    path("tickets/<int:ticket_id>/next-action/", TicketNextActionAPIView.as_view(), name="ticket-next-action"),
    path("resources/", ResourceListCreateAPIView.as_view(), name="resource-list-create"),
    path("resources/<int:resource_id>/", ResourceDetailAPIView.as_view(), name="resource-detail"),
    path("resources/<int:resource_id>/movements/", ResourceMovementAPIView.as_view(), name="resource-movements"),
    path("tickets/<int:ticket_id>/resources/", TicketResourceAssignmentAPIView.as_view(), name="ticket-resource-assignments"),
    path("resource-assignments/<int:assignment_id>/", ResourceAssignmentDetailAPIView.as_view(), name="resource-assignment-detail"),
    path("assets/", AssetListCreateAPIView.as_view(), name="asset-list-create"),
    path("assets/scan/resolve/", AssetScanResolveAPIView.as_view(), name="asset-scan-resolve"),
    path("assets/<int:asset_id>/", AssetDetailAPIView.as_view(), name="asset-detail"),
    path("assets/<int:asset_id>/identifiers/", AssetIdentifierCreateAPIView.as_view(), name="asset-identifier-create"),
    path("tickets/<int:ticket_id>/assets/", TicketAssetLinkAPIView.as_view(), name="ticket-asset-links"),
    path("ticket-conversations/", TicketConversationListAPIView.as_view(), name="ticket-conversation-list"),
    path("ticket-conversations/<int:ticket_id>/messages/", TicketConversationMessagesAPIView.as_view(), name="ticket-conversation-messages"),
    path("ticket-conversations/<int:ticket_id>/controls/", TicketConversationControlsAPIView.as_view(), name="ticket-conversation-controls"),
    path("communication-preferences/current/", CurrentCommunicationPreferenceAPIView.as_view(), name="communication-preferences-current"),
    # ----------------------------
    # SBO / Business Team Routes
    # ----------------------------
    path(
        "businesses/<int:pk>/members/",
        BusinessTeamViewSet.as_view({"get": "members"}),
        name="business-team-members",
    ),
    path(
        "businesses/<int:pk>/invite-employee/",
        BusinessTeamViewSet.as_view({"post": "invite_employee"}),
        name="business-invite-employee",
    ),
    path(
        "auth/employee-invites/accept/",
        EmployeeInviteAcceptViewSet.as_view({"post": "accept"}),
        name="employee-invites-accept",
    ),

    # ----------------------------
    # Me Business Cards
    # ----------------------------
    path("me/business-cards/resolve/", MeBusinessCardResolveAPIView.as_view(), name="me-business-cards-resolve"),

    # ----------------------------
    # PM Employee Invites
    # ----------------------------
    path(
        "pm/employees/invites/",
        PMEmployeeInviteViewSet.as_view({"get": "list", "post": "create"}),
        name="pm-employee-invites",
    ),
    path(
        "pm/employees/invites/accept/",
        PMEmployeeInviteViewSet.as_view({"post": "accept"}),
        name="pm-employee-invites-accept",
    ),

    # ----------------------------
    # PM Inbox
    # ----------------------------
    path(
        "pm/inbox/threads/",
        PMInboxThreadViewSet.as_view({"get": "list", "post": "create"}),
        name="pm-inbox-threads",
    ),
    path(
        "pm/inbox/threads/<int:pk>/",
        PMInboxThreadViewSet.as_view({"get": "retrieve", "patch": "partial_update"}),
        name="pm-inbox-thread-detail",
    ),
    path(
        "pm/inbox/threads/<int:pk>/messages/",
        PMInboxThreadViewSet.as_view({"get": "messages"}),
        name="pm-inbox-thread-messages",
    ),
    path(
        "pm/inbox/threads/<int:pk>/send/",
        PMInboxThreadViewSet.as_view({"post": "send"}),
        name="pm-inbox-thread-send",
    ),
    path(
        "pm/inbox/threads/<int:pk>/close/",
        PMInboxThreadViewSet.as_view({"post": "close"}),
        name="pm-inbox-thread-close",
    ),
    path(
        "pm/inbox/threads/<int:pk>/open/",
        PMInboxThreadViewSet.as_view({"post": "open"}),
        name="pm-inbox-thread-open",
    ),

    # ----------------------------
    # Investor Claim + Inbox
    # ----------------------------
    path("investor/claim/", InvestorClaimAPIView.as_view(), name="investor-claim"),
    path(
        "investor/inbox/threads/",
        InvestorInboxThreadViewSet.as_view({"get": "list"}),
        name="investor-inbox-threads",
    ),
    path(
        "investor/inbox/threads/<int:pk>/messages/",
        InvestorInboxThreadViewSet.as_view({"get": "messages"}),
        name="investor-inbox-thread-messages",
    ),
    path(
        "investor/inbox/threads/<int:pk>/send/",
        InvestorInboxThreadViewSet.as_view({"post": "send"}),
        name="investor-inbox-thread-send",
    ),

    # ----------------------------
    # Router Endpoints
    # ----------------------------
    path("", include(router.urls)),

    # ----------------------------
    # Compatibility: /api/v1/me/
    # ----------------------------
    path("me/", MeAPIView.as_view(), name="me-alias"),

    # ----------------------------
    # Tenant Invite Accept
    # ----------------------------
    path("tenant/invites/accept/", TenantInviteAcceptAPIView.as_view(), name="tenant-invite-accept"),

    # ----------------------------
    # PM Overview / Rent
    # ----------------------------
    path("pm/overview/summary/", PMOverviewSummaryAPIView.as_view(), name="pm-overview-summary"),
    path("pm/rent/webhook/", PMRentWebhookAPIView.as_view(), name="pm-rent-webhook"),

    # ----------------------------
    # Ticket Metrics
    # ----------------------------
    path("tickets/metrics/zip/", TicketZipMetricsAPIView.as_view(), name="tickets-metrics-zip"),

    # ----------------------------
    # Auth
    # ----------------------------
    path("auth/register/", RegisterAPIView.as_view(), name="auth-register"),
    path("auth/login/", TokenLoginAPIView.as_view(), name="auth-login"),
    path("auth/me/", MeAPIView.as_view(), name="auth-me"),
    path("auth/logout/", LogoutAPIView.as_view(), name="auth-logout"),
    path("auth/upgrade-to-sbo/", UpgradeToSboAPIView.as_view(), name="auth-upgrade-to-sbo"),
    path("auth/upgrade-to-sbo-promo/", UpgradeToSboPromoAPIView.as_view(), name="auth-upgrade-to-sbo-promo"),

    # ----------------------------
    # Bootstrap
    # ----------------------------
    path("bootstrap/my-business/", BootstrapMyBusinessAPIView.as_view(), name="bootstrap-my-business"),

    # ----------------------------
    # User Billing
    # ----------------------------
    path("billing/user/status/", UserBillingStatusAPIView.as_view(), name="billing-user-status"),
    path("billing/user/setup-card/", CreateUserSetupCheckoutSessionAPIView.as_view(), name="billing-user-setup-card"),
    path("billing/user/setup/", CreateUserSetupCheckoutSessionAPIView.as_view(), name="billing-user-setup"),

    # ----------------------------
    # Business Billing
    # ----------------------------
    path("billing/status/", BillingStatusAPIView.as_view(), name="billing-status"),
    path("billing/setup-card/", CreateSetupCheckoutSessionAPIView.as_view(), name="billing-setup-card"),
    path("billing/setup/", CreateSetupCheckoutSessionAPIView.as_view(), name="billing-setup"),
    path("billing/monthly/preview/", BillingPreviewAPIView.as_view(), name="billing-preview"),
    path("billing/monthly/create/", CreateOrUpdateMonthlyBillAPIView.as_view(), name="billing-create"),
    path("billing/unlock-request/", UnlockRequestAPIView.as_view(), name="billing-unlock-request"),

    # ----------------------------
    # Subscription
    # ----------------------------
    path("billing/subscription/status/", SubscriptionStatusAPIView.as_view(), name="sub-status"),
    path("billing/subscription/subscribe/", CreateSubscriptionCheckoutSessionAPIView.as_view(), name="sub-subscribe"),
    path("billing/subscription/cancel/", CancelSubscriptionAPIView.as_view(), name="sub-cancel"),

    # ----------------------------
    # Stripe Webhooks
    # ----------------------------
    path("stripe/webhook/", StripeWebhookAPIView.as_view(), name="stripe-webhook"),
    path("billing/webhook/", StripeWebhookAPIView.as_view(), name="billing-webhook"),

    # ----------------------------
    # Invoice Checkout
    # ----------------------------
    path(
        "billing/invoices/<int:invoice_id>/checkout/",
        CreateInvoiceCheckoutSessionAPIView.as_view(),
        name="invoice-checkout",
    ),
    path("billing/invoices/webhook/", InvoicePaymentWebhookAPIView.as_view(), name="invoice-webhook"),

    # ----------------------------
    # Platform KPIs / Metrics / Broadcasts
    # ----------------------------
    path("platform/kpis/", PlatformKPIAPIView.as_view(), name="platform-kpis"),
    path("platform/metrics/summary/", PlatformMetricsSummaryAPIView.as_view(), name="platform-metrics-summary"),
    path("platform/metrics/alerts/", PlatformMetricsAlertsAPIView.as_view(), name="platform-metrics-alerts"),
    path("platform/broadcasts/", PlatformBroadcastAPIView.as_view(), name="platform-broadcasts"),

    # ----------------------------
    # Stripe Connect Express
    # ----------------------------
    path("connect/express/start/", StripeConnectExpressStartAPIView.as_view(), name="connect-express-start"),
    path("connect/express/status/", StripeConnectExpressStatusAPIView.as_view(), name="connect-express-status"),

    # ----------------------------
    # SALES OS Compatibility Aliases
    # ----------------------------
    path("salesos/stages/", salesos_stage_list, name="salesos-stages"),
    path("salesos/stages/<int:pk>/", salesos_stage_detail, name="salesos-stage-detail"),
    path("sales-os/stages/", salesos_stage_list, name="sales-os-stages"),
    path("sales-os/stages/<int:pk>/", salesos_stage_detail, name="sales-os-stage-detail"),

    path("salesos/prospects/", salesos_prospect_list, name="salesos-prospects"),
    path("salesos/prospects/<int:pk>/", salesos_prospect_detail, name="salesos-prospect-detail"),
    path("sales-os/prospects/", salesos_prospect_list, name="sales-os-prospects"),
    path("sales-os/prospects/<int:pk>/", salesos_prospect_detail, name="sales-os-prospects-detail"),

    path("sales/leads/", salesos_prospect_list, name="sales-leads-alias"),
    path("sales/leads/<int:pk>/", salesos_prospect_detail, name="sales-leads-detail-alias"),

    path("salesos/pipelines/", salesos_pipeline_list, name="salesos-pipelines"),
    path("salesos/pipelines/<int:pk>/", salesos_pipeline_detail, name="salesos-pipeline-detail"),
    path("sales-os/pipelines/", salesos_pipeline_list, name="sales-os-pipelines"),
    path("sales-os/pipelines/<int:pk>/", salesos_pipeline_detail, name="sales-os-pipeline-detail"),
]
