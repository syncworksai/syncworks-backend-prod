"""
Core import hub for SyncWorks API viewsets.

If you want: user_accounts/urls.py can import from user_accounts.viewsets.core
instead of importing from many modules.

Rule:
- Keep canonical names here. If you rename a module/file, only update imports here.
"""

# --- Team + Me ---
from user_accounts.viewsets.team import TeamMembersViewSet, TeamInvitesViewSet
from user_accounts.viewsets.me import MeViewSet

# --- Auth ---
from user_accounts.viewsets.auth import (
    RegisterAPIView,
    TokenLoginAPIView,
    MeAPIView,
    LogoutAPIView,
)

# --- Platform Billing ---
from user_accounts.viewsets.platform_billing import (
    BillingStatusAPIView,
    CreateSetupCheckoutSessionAPIView,
    StripeWebhookAPIView,
    BillingPreviewAPIView,
    CreateOrUpdateMonthlyBillAPIView,
)

# --- Platform Admin KPIs / Console ---
from user_accounts.viewsets.platform_admin import PlatformKPIAPIView

from user_accounts.viewsets.platform_console import (
    PlatformUsersViewSet,
    PlatformBusinessesViewSet,
    PlatformBillingSummaryViewSet,
    PlatformKpiTimeseriesViewSet,
)

# --- Notifications + News Reel ---
from user_accounts.viewsets.notifications import (
    NotificationViewSet,
    MeNewsReelViewSet,
)

# --- Platform Broadcasts / News Reel Admin ---
from user_accounts.viewsets.platform_broadcasts import (
    PlatformBroadcastAPIView,
    PlatformNewsReelAdminViewSet,
)

# --- Categories + Marketplace Service Requests ---
from user_accounts.viewsets.categories import ServiceCategoryViewSet
from user_accounts.viewsets.marketplace import ServiceRequestViewSet

# --- Tickets + Messaging + Billing ---
from user_accounts.viewsets.tickets import (
    TicketViewSet,
    TicketMessageViewSet,
    TicketAttachmentViewSet,
    TicketQuoteViewSet,
    InvoiceViewSet,
)

# --- Bootstrap (dev) ---
from user_accounts.viewsets.bootstrap import BootstrapMyBusinessAPIView

__all__ = [
    # team/me
    "TeamMembersViewSet",
    "TeamInvitesViewSet",
    "MeViewSet",

    # auth
    "RegisterAPIView",
    "TokenLoginAPIView",
    "MeAPIView",
    "LogoutAPIView",

    # billing
    "BillingStatusAPIView",
    "CreateSetupCheckoutSessionAPIView",
    "StripeWebhookAPIView",
    "BillingPreviewAPIView",
    "CreateOrUpdateMonthlyBillAPIView",

    # platform
    "PlatformKPIAPIView",
    "PlatformUsersViewSet",
    "PlatformBusinessesViewSet",
    "PlatformBillingSummaryViewSet",
    "PlatformKpiTimeseriesViewSet",

    # notifications/news
    "NotificationViewSet",
    "MeNewsReelViewSet",

    # broadcasts/news admin
    "PlatformBroadcastAPIView",
    "PlatformNewsReelAdminViewSet",

    # marketplace
    "ServiceCategoryViewSet",
    "ServiceRequestViewSet",

    # tickets
    "TicketViewSet",
    "TicketMessageViewSet",
    "TicketAttachmentViewSet",
    "TicketQuoteViewSet",
    "InvoiceViewSet",

    # bootstrap
    "BootstrapMyBusinessAPIView",
]
