"""
Central model exports.
Import models like:
    from user_accounts.models import Business, BusinessMember, InviteCode, ServiceCategory
"""

from __future__ import annotations

from .user import User
from .profiles import CustomerProfile, SmallBusinessOwnerProfile, SubcontractorProfile

from .audit import AuditLog
from .notifications import Notification, PlatformNewsItem

from .categories import ServiceCategory
from .business import Business, BusinessMember, BusinessCategory, BusinessMemberRole

from .service_requests import ServiceRequest, ServiceRequestPhoto
from .tickets import Ticket, TicketMessage, TicketAttachment, TicketQuote, TicketViewEvent

# ✅ Job invoices (ticket invoices)
from .billing import Invoice

# ✅ Cash fee invoices (monthly platform fee on cash GMV)
from .cash_fee_invoice import CashFeeInvoice

from .connections import Connection
from .invites import InviteCode

from .templates import DocumentTemplate

# ✅ Business-based platform billing
from .platform_billing import PlatformBillingProfile, MonthlyPlatformBill

# ✅ NEW: User billing (card on file before business exists)
from .user_billing import UserBillingProfile

from .promo import PromoCode, PromoRedemption
from .kpis import PlatformDailyKpi, BusinessDailyKpi, MarketplaceCellDailyKpi

from .customer_settings import CustomerSettings
from .calendar_sync import CalendarAccount, TicketCalendarEvent

from .finance_ops import FinanceSnapshot, FinancePlan
from .favorites import FavoriteBusiness
from .stripe_connect import StripeConnectProfile

# ✅ NEW: Support Requests (God Mode Inbox + unlock requests)
from .support_requests import SupportRequest

# ✅ NEW: Business access control (lock/unlock)
from .business_access import BusinessAccessControl

# ✅ PM MODELS
from .pm_property import PMProperty
from .pm_unit import PMUnit
from .pm_tenant import PMTenant
from .pm_invite import PMInvite
from .pm_document import PMDocument

# ✅ Section 8
from .pm_section8 import PMSection8Case

# ✅ PM Billing + Rent
from .pm_billing_settings import PMBillingSettings
from .pm_rent import PMRentCharge, PMRentPayment, PMRentPaymentAllocation

# ✅ PM Employees
from .pm_employees import PMEmployee, PMEmployeeInvite

# ✅ PM Investor / Inbox / PM Notifications
from .pm_investor import PMInvestor, PMPropertyInvestor, PMInboxThread, PMInboxMessage, PMNotification

# ✅ Optional: investor connection model (supports either filename)
PMInvestorConnection = None
try:
    from .pm_investor_connections import PMInvestorConnection  # type: ignore
except Exception:
    try:
        from .pm_investor_connection import PMInvestorConnection  # type: ignore
    except Exception:
        PMInvestorConnection = None

# ✅ Work Orders
from .workorders import PMWorkOrder  # noqa: F401

# ----------------------------
# ✅ SALES OS — REQUIRED CORE EXPORTS (DO NOT SILENCE)
# ----------------------------
from .sales_os import (  # type: ignore
    SalesPipeline,
    SalesPipelineMember,
    ProspectStage,
    Prospect,
    ProspectAttachment,
)

# ----------------------------
# ✅ SALES OS — OPTIONAL/ADVANCED MODELS (SAFE OPTIONAL)
# ----------------------------
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

# ✅ SALES OS Calendar (optional)
SalesCalendarEvent = None
try:
    from .sales_calendar import SalesCalendarEvent  # type: ignore
except Exception:
    SalesCalendarEvent = None


__all__ = [
    "User",
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
    "ServiceRequest",
    "ServiceRequestPhoto",
    "Ticket",
    "TicketMessage",
    "TicketAttachment",
    "TicketQuote",
    "TicketViewEvent",
    "Invoice",
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
    "CalendarAccount",
    "TicketCalendarEvent",
    "FinanceSnapshot",
    "FinancePlan",
    "FavoriteBusiness",
    "StripeConnectProfile",
    "SupportRequest",
    "BusinessAccessControl",
    # PM
    "PMProperty",
    "PMUnit",
    "PMTenant",
    "PMInvite",
    "PMDocument",
    "PMSection8Case",
    # PM Rent
    "PMBillingSettings",
    "PMRentCharge",
    "PMRentPayment",
    "PMRentPaymentAllocation",
    # PM Employees
    "PMEmployee",
    "PMEmployeeInvite",
    # PM Investor + Inbox + PMNotification
    "PMInvestor",
    "PMPropertyInvestor",
    "PMInboxThread",
    "PMInboxMessage",
    "PMNotification",
    # Work Orders
    "PMWorkOrder",
    # ✅ Sales OS (core)
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