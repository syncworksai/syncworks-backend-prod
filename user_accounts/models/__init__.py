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
from .profiles import (
    CustomerProfile,
    SmallBusinessOwnerProfile,
    SubcontractorProfile,
)

from .audit import AuditLog
from .notifications import Notification, PlatformNewsItem

from .categories import ServiceCategory
from .business import (
    Business,
    BusinessMember,
    BusinessCategory,
    BusinessMemberRole,
)
from .service_catalog import ServiceCatalogItem

from .service_requests import (
    ServiceRequest,
    ServiceRequestPhoto,
)
from .tickets import (
    Ticket,
    TicketMessage,
    TicketAttachment,
    TicketQuote,
    TicketViewEvent,
)

# Job invoices
from .billing import Invoice, InvoiceLineItem

# Monthly platform fee invoices for externally collected revenue
from .cash_fee_invoice import CashFeeInvoice

from .connections import Connection
from .invites import InviteCode

from .templates import DocumentTemplate

# Business-level platform billing
from .platform_billing import (
    PlatformBillingProfile,
    MonthlyPlatformBill,
)

# User-level billing and subscription state
from .user_billing import UserBillingProfile

from .promo import PromoCode, PromoRedemption
from .kpis import (
    PlatformDailyKpi,
    BusinessDailyKpi,
    MarketplaceCellDailyKpi,
)

from .customer_settings import CustomerSettings
from .communication_preferences import CommunicationPreference
from .ticket_conversation_read_state import TicketConversationReadState
from .assets import AssetIdentifier, TicketAssetLink, TrackableAsset
from .calendar_sync import (
    CalendarAccount,
    TicketCalendarEvent,
)

from .finance_ops import FinanceSnapshot, FinancePlan
from .favorites import FavoriteBusiness
from .stripe_connect import StripeConnectProfile

from .support_requests import SupportRequest
from .business_access import BusinessAccessControl

# Property management
from .pm_property import PMProperty
from .pm_unit import PMUnit
from .pm_tenant import PMTenant
from .pm_invite import PMInvite
from .pm_document import PMDocument
from .pm_section8 import PMSection8Case

# Property management billing and rent
from .pm_billing_settings import PMBillingSettings
from .pm_rent import (
    PMRentCharge,
    PMRentPayment,
    PMRentPaymentAllocation,
)

# Property management employees
from .pm_employees import (
    PMEmployee,
    PMEmployeeInvite,
)

# Property management investors, inbox, and notifications
from .pm_investor import (
    PMInvestor,
    PMPropertyInvestor,
    PMInboxThread,
    PMInboxMessage,
    PMNotification,
)

# Optional investor connection model
PMInvestorConnection = None

try:
    from .pm_investor_connections import PMInvestorConnection  # type: ignore
except Exception:
    try:
        from .pm_investor_connection import PMInvestorConnection  # type: ignore
    except Exception:
        PMInvestorConnection = None

# Work orders
from .workorders import PMWorkOrder

# Sales core models
from .sales_os import (
    SalesPipeline,
    SalesPipelineMember,
    ProspectStage,
    Prospect,
    ProspectAttachment,
)

# Optional sales models
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

# Optional sales calendar
SalesCalendarEvent = None

try:
    from .sales_calendar import SalesCalendarEvent  # type: ignore
except Exception:
    SalesCalendarEvent = None


__all__ = [
    "User",
    "EmailVerificationChallenge",
    "CustomerProfile",
    "SmallBusinessOwnerProfile",
    "SubcontractorProfile",
    "AuditLog",
    "Notification",
    "PlatformNewsItem",
    "ServiceCategory",
    "BusinessCategory",
    "Business",
    "BusinessMember",
    "BusinessMemberRole",
    "ServiceCatalogItem",
    "ServiceRequest",
    "ServiceRequestPhoto",
    "Ticket",
    "TicketMessage",
    "TicketAttachment",
    "TicketQuote",
    "TicketViewEvent",
    "Invoice",
    "InvoiceLineItem",
    "CashFeeInvoice",
    "Connection",
    "InviteCode",
    "DocumentTemplate",
    "PlatformBillingProfile",
    "MonthlyPlatformBill",
    "UserBillingProfile",
    "PromoCode",
    "PromoRedemption",
    "PlatformDailyKpi",
    "BusinessDailyKpi",
    "MarketplaceCellDailyKpi",
    "CustomerSettings",
    "CommunicationPreference",
    "TicketConversationReadState",
    "TicketAssetLink",
    "AssetIdentifier",
    "TrackableAsset",
    "CalendarAccount",
    "TicketCalendarEvent",
    "FinanceSnapshot",
    "FinancePlan",
    "FavoriteBusiness",
    "StripeConnectProfile",
    "SupportRequest",
    "BusinessAccessControl",
    # Property management
    "PMProperty",
    "PMUnit",
    "PMTenant",
    "PMInvite",
    "PMDocument",
    "PMSection8Case",
    "PMBillingSettings",
    "PMRentCharge",
    "PMRentPayment",
    "PMRentPaymentAllocation",
    "PMEmployee",
    "PMEmployeeInvite",
    "PMInvestor",
    "PMPropertyInvestor",
    "PMInboxThread",
    "PMInboxMessage",
    "PMNotification",
    "PMWorkOrder",
    # Sales
    "SalesPipeline",
    "SalesPipelineMember",
    "ProspectStage",
    "Prospect",
    "ProspectAttachment",
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