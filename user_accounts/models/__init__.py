"""
Central model exports.

Import models like:

    from user_accounts.models import (
        Business,
        BusinessMember,
        InviteCode,
        ServiceCategory,
    )
"""

from __future__ import annotations

from .user import User, EmailVerificationChallenge
from .profiles import CustomerProfile, SmallBusinessOwnerProfile, SubcontractorProfile
from .identity import PersonalIdentity, UserLocation, BusinessVerification
from .audit import AuditLog
from .notifications import Notification, PlatformNewsItem
from .categories import ServiceCategory
from .business import Business, BusinessMember, BusinessCategory, BusinessMemberRole
from .professional_services import ProfessionalPracticeProfile, ProfessionalProvider, ProfessionalResource, ProfessionalAppointment
from .workforce import WorkforceProfile, TicketOperationalProfile
from .service_catalog import ServiceCatalogItem
from .business_customers import BusinessCustomer
from .data_imports import BusinessDataImport
from .projects import BusinessProject
from .partner_network import BusinessPartnerInvitation, BusinessPartnerRelationship
from .partner_work_tickets import PartnerWorkTicket
from .partner_financials import PartnerWorkChangeOrder, PartnerWorkEstimate
from .partner_billing import PartnerInvoice, PartnerPayment, PartnerPaymentAllocation
from .service_requests import ServiceRequest, ServiceRequestPhoto
from .tickets import Ticket, TicketMessage, TicketAttachment, TicketQuote, TicketViewEvent
from .billing import Invoice, InvoiceLineItem
from .invoice_experience import InvoiceEvent
from .cash_fee_invoice import CashFeeInvoice
from .connections import Connection
from .invites import InviteCode
from .templates import DocumentTemplate
from .platform_billing import PlatformBillingProfile, MonthlyPlatformBill
from .user_billing import UserBillingProfile
from .promo import PromoCode, PromoRedemption
from .kpis import PlatformDailyKpi, BusinessDailyKpi, MarketplaceCellDailyKpi
from .customer_settings import CustomerSettings
from .communication_preferences import CommunicationPreference
from .ticket_conversation_read_state import TicketConversationReadState
from .assets import AssetIdentifier, TicketAssetLink, TrackableAsset
from .resources import BusinessResource, ResourceAssignment, ResourceMovement
from .workflow import TicketDependency, TicketRequirement
from .operations import OperationalAlert, OperationalEvent, TicketETA
from .automation import AutomationExecution, AutomationRule
from .inventory import InventoryItem, InventoryLocation, InventoryStock, PurchaseOrder, PurchaseOrderLine, PurchaseReceipt, StockMovement, Vendor
from .calendar_sync import CalendarAccount, TicketCalendarEvent
from .finance_ops import FinanceSnapshot, FinancePlan
from .personal_finance import FinanceAccount, FinanceBudget, FinanceConnection, FinanceGoal, FinanceLiability, FinanceObligation, FinanceTransaction
from .favorites import FavoriteBusiness
from .stripe_connect import StripeConnectProfile
from .support_requests import SupportRequest
from .business_access import BusinessAccessControl
from .pm_property import PMProperty
from .pm_unit import PMUnit
from .pm_tenant import PMTenant
from .pm_invite import PMInvite
from .pm_document import PMDocument
from .pm_section8 import PMSection8Case
from .pm_billing_settings import PMBillingSettings
from .pm_rent import PMRentCharge, PMRentPayment, PMRentPaymentAllocation
from .pm_employees import PMEmployee, PMEmployeeInvite
from .pm_investor import PMInvestor, PMPropertyInvestor, PMInboxThread, PMInboxMessage, PMNotification

PMInvestorConnection = None
try:
    from .pm_investor_connections import PMInvestorConnection  # type: ignore
except Exception:
    try:
        from .pm_investor_connection import PMInvestorConnection  # type: ignore
    except Exception:
        PMInvestorConnection = None

from .workorders import PMWorkOrder
from .sales_os import SalesPipeline, SalesPipelineMember, ProspectStage, Prospect, ProspectAttachment

ProspectActivity = None
SalesMemberEmailSettings = None
ProspectEmailLog = None
try:
    from .sales_os import ProspectActivity  # type: ignore
except Exception:
    ProspectActivity = None
try:
    from .sales_os import SalesMemberEmailSettings  # type: ignore
except Exception:
    SalesMemberEmailSettings = None
try:
    from .sales_os import ProspectEmailLog  # type: ignore
except Exception:
    ProspectEmailLog = None

SalesCalendarEvent = None
try:
    from .sales_calendar import SalesCalendarEvent  # type: ignore
except Exception:
    SalesCalendarEvent = None

__all__ = [
    "User", "EmailVerificationChallenge", "CustomerProfile", "SmallBusinessOwnerProfile", "SubcontractorProfile",
    "PersonalIdentity", "UserLocation", "BusinessVerification",
    "AuditLog", "Notification", "PlatformNewsItem", "ServiceCategory", "BusinessCategory", "Business",
    "BusinessMember", "BusinessMemberRole", "ProfessionalPracticeProfile", "ProfessionalProvider", "ProfessionalResource", "ProfessionalAppointment",
    "WorkforceProfile", "TicketOperationalProfile",
    "ServiceCatalogItem", "BusinessCustomer", "BusinessDataImport",
    "BusinessProject", "BusinessPartnerRelationship", "PartnerWorkTicket", "PartnerWorkChangeOrder",
    "PartnerPaymentAllocation", "PartnerPayment", "PartnerInvoice", "PartnerWorkEstimate", "BusinessPartnerInvitation",
    "ServiceRequest", "ServiceRequestPhoto", "Ticket", "TicketMessage", "TicketAttachment", "TicketQuote",
    "TicketViewEvent", "Invoice", "InvoiceLineItem", "InvoiceEvent", "CashFeeInvoice", "Connection", "InviteCode", "DocumentTemplate",
    "PlatformBillingProfile", "MonthlyPlatformBill", "UserBillingProfile", "PromoCode", "PromoRedemption",
    "PlatformDailyKpi", "BusinessDailyKpi", "MarketplaceCellDailyKpi", "CustomerSettings", "CommunicationPreference",
    "TicketConversationReadState", "TicketAssetLink", "AssetIdentifier", "TrackableAsset", "ResourceMovement",
    "ResourceAssignment", "BusinessResource", "TicketDependency", "TicketRequirement", "TicketETA", "OperationalEvent",
    "OperationalAlert", "AutomationRule", "AutomationExecution", "Vendor", "StockMovement", "PurchaseReceipt",
    "PurchaseOrderLine", "PurchaseOrder", "InventoryStock", "InventoryLocation", "InventoryItem", "CalendarAccount",
    "TicketCalendarEvent", "FinanceSnapshot", "FinancePlan", "FinanceConnection", "FinanceAccount", "FinanceLiability",
    "FinanceObligation", "FinanceTransaction", "FinanceGoal", "FinanceBudget", "FavoriteBusiness", "StripeConnectProfile",
    "SupportRequest", "BusinessAccessControl", "PMProperty", "PMUnit", "PMTenant", "PMInvite", "PMDocument",
    "PMSection8Case", "PMBillingSettings", "PMRentCharge", "PMRentPayment", "PMRentPaymentAllocation", "PMEmployee",
    "PMEmployeeInvite", "PMInvestor", "PMPropertyInvestor", "PMInboxThread", "PMInboxMessage", "PMNotification",
    "PMWorkOrder", "SalesPipeline", "SalesPipelineMember", "ProspectStage", "Prospect", "ProspectAttachment",
]

if PMInvestorConnection is not None:
    __all__.append("PMInvestorConnection")
if ProspectActivity is not None:
    __all__.append("ProspectActivity")
if SalesMemberEmailSettings is not None:
    __all__.append("SalesMemberEmailSettings")
if ProspectEmailLog is not None:
    __all__.append("ProspectEmailLog")
if SalesCalendarEvent is not None:
    __all__.append("SalesCalendarEvent")
