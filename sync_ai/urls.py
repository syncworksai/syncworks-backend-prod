from .forge_memory_views import ForgeProfileView, ForgeHistoryView
from .forge_reflection_views import ForgeReflectionView
from django.urls import path
from .assist_pilot_views import SyncAssistPilotControlView, SyncAssistPilotDecisionView, SyncAssistPilotScanView
from .assist_workday_views import SyncAssistWorkdayView, SyncAssistWorkdayProgressView, SyncAssistWorkdayRunView
from .assist_job_views import SyncAssistJobView, SyncAssistJobCancelView
from .assist_budget_views import SyncAssistBudgetView
from .assist_delegation_views import SyncAssistDelegationView
from .assist_team_views import SyncAssistTeamView
from .assist_assignment_views import SyncAssistAssignmentsView, SyncAssistAssignmentDecisionView, SyncAssistEmployeeWorkView
from .assist_manual_tests import SyncAssistManualRoleTestView
from .assist_weekly_schedule_views import VictoriaWeeklyPlanView
from .assist_work_history import SyncAssistWorkHistoryView
from .assist_communications_views import SyncAssistCommunicationsView, SyncAssistWhatsAppInboundView
from .assist_internal_connections import SyncAssistInternalConnectionsView
from .assist_growth_prospects import SyncAssistGrowthProspectsView, SyncAssistGrowthProspectStageView
from .assist_growth_operations_views import SyncAssistGrowthCampaignView, SyncAssistOperationsBriefView
from .assist_daily_views import SyncAssistDailyView, SyncAssistDailyItemView
from .assist_chief_views import JarvisCasesView, JarvisCaseDecisionView, JarvisChiefBriefingView
from .assist_outlook_views import OutlookStatus, OutlookConnect, OutlookCallback, OutlookInbox, OutlookDraft, OutlookSend, OutlookDisconnect
from .assist_email_intelligence import JarvisWritingPreferencesView, JarvisOutlookSuggestView, JarvisOutlookBriefView

from user_accounts.viewsets.invoice_experience import (
    BusinessInvoiceActionView,
    BusinessInvoiceCenterView,
    BusinessInvoiceDetailView,
    BusinessInvoiceFromTicketView,
)
from user_accounts.viewsets.invoice_automation import BusinessInvoiceAutomationSettingsView, BusinessReceivablesIntelligenceView
from .assistant_connection_views import SyncAssistantGeocodeView, SyncAssistantInboxStateView
from .assistant_daily_state_views import SyncAssistantDailyStateView, SyncAssistantDepartureReminderView
from .billing_runtime_views import BillingRuntimeAPIView
from .briefing_views import SyncGodModeBriefingView, SyncRoleAwareBriefingView
from .dispatch_views import BusinessDispatchBoardView, BusinessDispatchDelayView
from .drive_state_views import SyncAssistantDriveStateView
from .health_views import LivenessView, ReadinessView
from .invoice_customer_views import CustomerInvoiceCenterView, CustomerInvoiceDetailView
from .live_operations_views import BusinessLiveOperationsView, EmployeeJobClockView, EmployeeLiveDayView
from .jarvis_product_views import UserJarvisCheckInView, UserJarvisCheckOutView, UserJarvisCheckoutView, UserJarvisPortalView, UserJarvisProfileView, UserJarvisWebhookView, UserSyncAssistantLiveCheckoutView
from .local_intelligence_views import SyncLocalIntelligenceView
from .marketplace_views import MarketplaceAvailabilityView, MarketplaceBookView
from .notification_views import SyncNotificationRefreshView, SyncNotificationSettingsView, SyncPushDeviceView
from .professional_services_views import BusinessProfessionalAppointmentsView, CustomerProfessionalAppointmentResponseView, CustomerProfessionalAppointmentsView, ProfessionalAvailabilityView, ProfessionalDiscoveryView, ProfessionalPracticeSettingsView, ProfessionalProviderDetailView, ProfessionalProvidersView, ProfessionalResourceDetailView, ProfessionalResourcesView
from .production_readiness_views import ProductionReadinessAPIView
from .workforce_views import BusinessOperationsSummaryView, BusinessWorkforceView, TicketOperationsView, BusinessTechnicianGroupsView
from .views import SyncAIActionDraftView, SyncAIChatView, SyncAIStatusView, SyncAITicketReplyExecuteView
from .workflow_intake import SyncWorkflowIntakePreviewView, SyncWorkflowPMWorkOrderCreateView
from .voice_views import SyncVoiceStatusView, SyncVoiceSynthesizeView

urlpatterns = [
    path("assist/pilot/manual-tests/", SyncAssistManualRoleTestView.as_view(), name="assist-manual-role-tests"),
    path('assist/pilot/assignments/<str:assignment_id>/weekly-plan/', VictoriaWeeklyPlanView.as_view(), name='assist-victoria-weekly-plan'),
    path('assist/pilot/assignments/', SyncAssistAssignmentsView.as_view(), name='assist-assignments'),
    path('assist/pilot/employees/<str:role>/work/', SyncAssistEmployeeWorkView.as_view(), name='assist-employee-work'),
    path('assist/pilot/assignments/<str:assignment_id>/decision/', SyncAssistAssignmentDecisionView.as_view(), name='assist-assignment-decision'),
    path('business/technician-groups/', BusinessTechnicianGroupsView.as_view(), name='business-technician-groups'),
    path('assist/pilot/delegate/', SyncAssistDelegationView.as_view(), name='sync-assist-delegate'),
    path('assist/pilot/budget/', SyncAssistBudgetView.as_view(), name='sync-assist-pilot-budget'),
    path('forge/reflection/', ForgeReflectionView.as_view(), name='forge-reflection'),
    path('forge/profile/', ForgeProfileView.as_view(), name='forge-profile'),
    path('forge/history/', ForgeHistoryView.as_view(), name='forge-history'),
    path("assist/pilot/workday/history/", SyncAssistWorkHistoryView.as_view(), name="sync-assist-work-history"),
    path("assist/pilot/team/", SyncAssistTeamView.as_view(), name="sync-assist-team-config"),
    path("assist/pilot/workday/<str:goal_id>/run/", SyncAssistWorkdayRunView.as_view(), name="sync-assist-workday-run"),
    path("assist/pilot/workday/jobs/", SyncAssistJobView.as_view(), name="sync-assist-background-jobs"),
    path("assist/pilot/workday/jobs/<str:goal_id>/cancel/", SyncAssistJobCancelView.as_view(), name="sync-assist-job-cancel"),
    path("assist/pilot/workday/", SyncAssistWorkdayView.as_view(), name="sync-assist-workday"),
    path("assist/pilot/workday/<str:goal_id>/steps/<str:step_id>/", SyncAssistWorkdayProgressView.as_view(), name="sync-assist-workday-progress"),
    path("assist/pilot/chief/brief/", JarvisChiefBriefingView.as_view(), name="assist-chief-brief"),
    path("assist/pilot/chief/cases/", JarvisCasesView.as_view(), name="assist-chief-cases"),
    path("assist/pilot/chief/cases/<str:case_id>/decision/", JarvisCaseDecisionView.as_view(), name="assist-chief-case-decision"),
    path("assist/pilot/chief-of-staff/preferences/", JarvisWritingPreferencesView.as_view(), name="assist-chief-preferences"),
    path("assist/pilot/outlook/suggest/", JarvisOutlookSuggestView.as_view(), name="assist-outlook-suggest"),
    path("assist/pilot/outlook/brief/", JarvisOutlookBriefView.as_view(), name="assist-outlook-brief"),
    path("assist/pilot/outlook/status/", OutlookStatus.as_view(), name="assist-outlook-status"),
    path("assist/pilot/outlook/connect/", OutlookConnect.as_view(), name="assist-outlook-connect"),
    path("assist/pilot/outlook/callback/", OutlookCallback.as_view(), name="assist-outlook-callback"),
    path("assist/pilot/outlook/inbox/", OutlookInbox.as_view(), name="assist-outlook-inbox"),
    path("assist/pilot/outlook/draft/", OutlookDraft.as_view(), name="assist-outlook-draft"),
    path("assist/pilot/outlook/send/", OutlookSend.as_view(), name="assist-outlook-send"),
    path("assist/pilot/outlook/disconnect/", OutlookDisconnect.as_view(), name="assist-outlook-disconnect"),
    path("assist/pilot/daily/", SyncAssistDailyView.as_view(), name="assist-daily"),
    path("assist/pilot/daily/item/", SyncAssistDailyItemView.as_view(), name="assist-daily-item"),
    path("assist/pilot/growth/campaign/", SyncAssistGrowthCampaignView.as_view(), name="assist-growth-campaign"),
    path("assist/pilot/operations/brief/", SyncAssistOperationsBriefView.as_view(), name="assist-operations-brief"),
    path("assist/pilot/growth/prospects/", SyncAssistGrowthProspectsView.as_view(), name="assist-growth-prospects"),
    path("assist/pilot/growth/prospects/<str:prospect_id>/stage/", SyncAssistGrowthProspectStageView.as_view(), name="assist-growth-stage"),
    path("assist/pilot/internal-connections/", SyncAssistInternalConnectionsView.as_view(), name="sync-assist-internal-connections"),
    path("assist/pilot/communications/", SyncAssistCommunicationsView.as_view(), name="sync-assist-communications"),
    path("assist/pilot/whatsapp/inbound/", SyncAssistWhatsAppInboundView.as_view(), name="sync-assist-whatsapp-inbound"),
    path("assist/pilot/", SyncAssistPilotControlView.as_view(), name="sync-assist-pilot-control"),
    path("assist/pilot/scan/", SyncAssistPilotScanView.as_view(), name="sync-assist-pilot-scan"),
    path("assist/pilot/tasks/<str:task_id>/decision/", SyncAssistPilotDecisionView.as_view(), name="sync-assist-pilot-decision"),
    path("status/", SyncAIStatusView.as_view(), name="sync-ai-status"),
    path("health/live/", LivenessView.as_view(), name="sync-health-live"),
    path("health/ready/", ReadinessView.as_view(), name="sync-health-ready"),
    path("production/readiness/", ProductionReadinessAPIView.as_view(), name="sync-production-readiness"),
    path("chat/", SyncAIChatView.as_view(), name="sync-ai-chat"),
    path("workflows/preview/", SyncWorkflowIntakePreviewView.as_view(), name="sync-workflow-intake-preview"),
    path("workflows/pm-work-order/create/", SyncWorkflowPMWorkOrderCreateView.as_view(), name="sync-workflow-pm-create"),
    path("local-intelligence/", SyncLocalIntelligenceView.as_view(), name="sync-local-intelligence"),
    path("briefing/", SyncRoleAwareBriefingView.as_view(), name="sync-role-aware-briefing"),
    path("briefing/god-mode/", SyncGodModeBriefingView.as_view(), name="sync-god-mode-briefing"),
    path("marketplace/availability/", MarketplaceAvailabilityView.as_view(), name="sync-marketplace-availability"),
    path("marketplace/book/", MarketplaceBookView.as_view(), name="sync-marketplace-book"),
    path("business/workforce/", BusinessWorkforceView.as_view(), name="sync-business-workforce"),
    path("business/operations/summary/", BusinessOperationsSummaryView.as_view(), name="sync-business-operations-summary"),
    path("business/tickets/<int:ticket_id>/operations/", TicketOperationsView.as_view(), name="sync-business-ticket-operations"),
    path("business/dispatch/", BusinessDispatchBoardView.as_view(), name="sync-business-dispatch"),
    path("business/dispatch/<int:ticket_id>/delay/", BusinessDispatchDelayView.as_view(), name="sync-business-dispatch-delay"),
    path("business/live-operations/", BusinessLiveOperationsView.as_view(), name="sync-business-live-operations"),
    path("employee/live-day/", EmployeeLiveDayView.as_view(), name="sync-employee-live-day"),
    path("employee/jobs/<int:ticket_id>/clock/", EmployeeJobClockView.as_view(), name="sync-employee-job-clock"),
    path("business/invoices/", BusinessInvoiceCenterView.as_view(), name="sync-business-invoice-center"),
    path("business/invoices/<int:invoice_id>/", BusinessInvoiceDetailView.as_view(), name="sync-business-invoice-detail"),
    path("business/invoices/from-ticket/<int:ticket_id>/", BusinessInvoiceFromTicketView.as_view(), name="sync-business-invoice-from-ticket"),
    path("business/invoices/<int:invoice_id>/<str:action_name>/", BusinessInvoiceActionView.as_view(), name="sync-business-invoice-action"),
    path("business/billing-automation/", BusinessInvoiceAutomationSettingsView.as_view(), name="sync-business-billing-automation"),
    path("business/receivables/", BusinessReceivablesIntelligenceView.as_view(), name="sync-business-receivables"),
    path("billing/runtime/run/", BillingRuntimeAPIView.as_view(), name="sync-billing-runtime"),
    path("customer/invoices/", CustomerInvoiceCenterView.as_view(), name="sync-customer-invoice-center"),
    path("customer/invoices/<int:invoice_id>/", CustomerInvoiceDetailView.as_view(), name="sync-customer-invoice-detail"),
    path("professional/discover/", ProfessionalDiscoveryView.as_view(), name="professional-discover"),
    path("professional/business/practice/", ProfessionalPracticeSettingsView.as_view(), name="professional-business-practice"),
    path("professional/business/providers/", ProfessionalProvidersView.as_view(), name="professional-business-providers"),
    path("professional/business/providers/<int:provider_id>/", ProfessionalProviderDetailView.as_view(), name="professional-business-provider-detail"),
    path("professional/business/resources/", ProfessionalResourcesView.as_view(), name="professional-business-resources"),
    path("professional/business/resources/<int:resource_id>/", ProfessionalResourceDetailView.as_view(), name="professional-business-resource-detail"),
    path("professional/business/availability/", ProfessionalAvailabilityView.as_view(), name="professional-business-availability"),
    path("professional/business/appointments/", BusinessProfessionalAppointmentsView.as_view(), name="professional-business-appointments"),
    path("professional/customer/appointments/", CustomerProfessionalAppointmentsView.as_view(), name="professional-customer-appointments"),
    path("professional/customer/appointments/<int:appointment_id>/respond/", CustomerProfessionalAppointmentResponseView.as_view(), name="professional-customer-appointment-respond"),
    path("assistant/profile/", UserJarvisProfileView.as_view(), name="sync-assistant-profile"),
    path("assistant/check-in/", UserJarvisCheckInView.as_view(), name="sync-assistant-check-in"),
    path("assistant/check-out/", UserJarvisCheckOutView.as_view(), name="sync-assistant-check-out"),
    path("assistant/daily-state/", SyncAssistantDailyStateView.as_view(), name="sync-assistant-daily-state"),
    path("assistant/drive-state/", SyncAssistantDriveStateView.as_view(), name="sync-assistant-drive-state"),
    path("assistant/location/geocode/", SyncAssistantGeocodeView.as_view(), name="sync-assistant-geocode"),
    path("assistant/inbox-state/", SyncAssistantInboxStateView.as_view(), name="sync-assistant-inbox-state"),
    path("assistant/notifications/", SyncNotificationSettingsView.as_view(), name="sync-assistant-notifications"),
    path("assistant/notifications/refresh/", SyncNotificationRefreshView.as_view(), name="sync-assistant-notifications-refresh"),
    path("assistant/notifications/device/", SyncPushDeviceView.as_view(), name="sync-assistant-push-device"),
    path("assistant/calendar/<int:event_id>/departure-reminder/", SyncAssistantDepartureReminderView.as_view(), name="sync-assistant-departure-reminder"),
    path("assistant/billing/checkout/", UserJarvisCheckoutView.as_view(), name="sync-assistant-checkout"),
    path("assistant/billing/live/checkout/", UserSyncAssistantLiveCheckoutView.as_view(), name="sync-assistant-live-checkout"),
    path("assistant/billing/portal/", UserJarvisPortalView.as_view(), name="sync-assistant-portal"),
    path("assistant/billing/webhook/", UserJarvisWebhookView.as_view(), name="sync-assistant-webhook"),
    path("jarvis/profile/", UserJarvisProfileView.as_view(), name="user-jarvis-profile"),
    path("jarvis/check-in/", UserJarvisCheckInView.as_view(), name="user-jarvis-check-in"),
    path("jarvis/check-out/", UserJarvisCheckOutView.as_view(), name="user-jarvis-check-out"),
    path("jarvis/billing/checkout/", UserJarvisCheckoutView.as_view(), name="user-jarvis-checkout"),
    path("jarvis/billing/portal/", UserJarvisPortalView.as_view(), name="user-jarvis-portal"),
    path("jarvis/billing/webhook/", UserJarvisWebhookView.as_view(), name="user-jarvis-webhook"),
    path("voice/status/", SyncVoiceStatusView.as_view(), name="sync-voice-status"),
    path("voice/synthesize/", SyncVoiceSynthesizeView.as_view(), name="sync-voice-synthesize"),
    path("actions/prepare/", SyncAIActionDraftView.as_view(), name="sync-ai-action-prepare"),
    path("actions/ticket-reply/execute/", SyncAITicketReplyExecuteView.as_view(), name="sync-ai-ticket-reply-execute"),
]
