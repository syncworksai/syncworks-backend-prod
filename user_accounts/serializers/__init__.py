# backend/user_accounts/serializers/__init__.py
from .auth import RegisterSerializer, TokenLoginSerializer
from .users import UserMeSerializer

from .categories import ServiceCategorySerializer
from .business import BusinessSerializer
from .business_customers import BusinessCustomerSerializer
from .connections import ConnectionSerializer

from .tickets import (
    ServiceRequestCreateSerializer,
    ServiceRequestSerializer,
    TicketSerializer,
    TicketMessageSerializer,
    TicketAttachmentSerializer,
    TicketQuoteSerializer,
    InvoiceSerializer,
    EligibleBusinessSerializer,
)

# Existing platform notifications (do NOT remove)
from .notifications import NotificationSerializer, PlatformNewsItemSerializer

from .admin import AdminUserSerializer

from .team import (
    BusinessMemberSerializer,
    InviteCodeSerializer,
    InviteAcceptSerializer,
)

# ✅ NEW: PM Investor / Inbox / Notifications
from .pm_investor import (
    PMInvestorSerializer,
    PMPropertyInvestorSerializer,
    PMInboxThreadSerializer,
    PMInboxMessageSerializer,
    PMNotificationSerializer,
)

__all__ = [
    "RegisterSerializer",
    "TokenLoginSerializer",
    "UserMeSerializer",

    "ServiceCategorySerializer",

    "BusinessSerializer",
    "BusinessCustomerSerializer",
    "BusinessMemberSerializer",

    "ConnectionSerializer",

    "InviteCodeSerializer",
    "InviteAcceptSerializer",

    "ServiceRequestCreateSerializer",
    "ServiceRequestSerializer",
    "TicketSerializer",
    "EligibleBusinessSerializer",

    "TicketMessageSerializer",
    "TicketAttachmentSerializer",

    # Existing platform notifications
    "NotificationSerializer",
    "PlatformNewsItemSerializer",

    "TicketQuoteSerializer",
    "InvoiceSerializer",

    "AdminUserSerializer",

    # ✅ NEW exports
    "PMInvestorSerializer",
    "PMPropertyInvestorSerializer",
    "PMInboxThreadSerializer",
    "PMInboxMessageSerializer",
    "PMNotificationSerializer",
]
