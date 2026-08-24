from django.urls import path

from user_accounts.viewsets.invoice_experience import (
    BusinessInvoiceActionView,
    BusinessInvoiceCenterView,
    BusinessInvoiceDetailView,
    BusinessInvoiceFromTicketView,
)
from user_accounts.viewsets.invoice_automation import BusinessInvoiceAutomationSettingsView, BusinessReceivablesIntelligenceView
from .assistant_connection_views import SyncAssistantGeocodeView, SyncAssistantInboxStateView
from .assistant_daily_state_views import SyncAssistantDailyStateView, SyncAssistantDepartureReminderView
from .briefing_views import SyncGodModeBriefingView, SyncRoleAwareBriefingView
from .dispatch_views import BusinessDispatchBoardView, BusinessDispatchDelayView
from .invoice_customer_views import CustomerInvoiceCenterView, CustomerInvoiceDetailView
from .live_operations_views import BusinessLiveOperationsView, EmployeeJobClockView, EmployeeLiveDayView
from .jarvis_product_views import UserJarvisCheckInView, UserJarvisCheckOutView, UserJarvisCheckoutView, UserJarvisPortalView, UserJarvisProfileView, UserJarvisWebhookView, UserSyncAssistantLiveCheckoutView
from .local_intelligence_views import SyncLocalIntelligenceView
from .marketplace_views import MarketplaceAvailabilityView, MarketplaceBookView
from .notification_views import SyncNotificationRefreshView, SyncNotificationSettingsView, SyncPushDeviceView
from .professional_services_views import BusinessProfessionalAppointmentsView, CustomerProfessionalAppointmentResponseView, CustomerProfessionalAppointmentsView, ProfessionalAvailabilityView, ProfessionalDiscoveryView, ProfessionalPracticeSettingsView, ProfessionalProviderDetailView, ProfessionalProvidersView, ProfessionalResourceDetailView, ProfessionalResourcesView
from .workforce_views import BusinessOperationsSummaryView, BusinessWorkforceView, TicketOperationsView
from .views import SyncAIActionDraftView, SyncAIChatView, SyncAIStatusView, SyncAITicketReplyExecuteView
from .voice_views import SyncVoiceStatusView, SyncVoiceSynthesizeView

urlpatterns = [
    path("status/", SyncAIStatusView.as_view(), name="sync-ai-status"),
    path("chat/", SyncAIChatView.as_view(), name="sync-ai-chat"),
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
