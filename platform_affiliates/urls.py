from __future__ import annotations

from django.urls import path

from platform_affiliates.views.affiliate_portal import (
    AffiliateMeBusinessesView,
    AffiliateMeCommissionsView,
    AffiliateMeView,
)
from platform_affiliates.views.godmode_affiliates import (
    GodModeAffiliateDetailView,
    GodModeAffiliateListCreateView,
    GodModeAffiliateOverviewView,
    GodModeAssignBusinessView,
)
from platform_affiliates.views.godmode_payouts import (
    GodModePayoutBatchListCreateView,
    GodModePayoutBatchMarkPaidView,
)
from platform_affiliates.views.tracking import (
    ResolveAffiliateCodeView,
    TrackAffiliateClickView,
)

urlpatterns = [
    # Affiliate portal
    path(
        "me/",
        AffiliateMeView.as_view(),
        name="affiliate-me",
    ),
    path(
        "me/businesses/",
        AffiliateMeBusinessesView.as_view(),
        name="affiliate-me-businesses",
    ),
    path(
        "me/commissions/",
        AffiliateMeCommissionsView.as_view(),
        name="affiliate-me-commissions",
    ),

    # Tracking
    path(
        "track-click/",
        TrackAffiliateClickView.as_view(),
        name="affiliate-track-click",
    ),
    path(
        "resolve-code/",
        ResolveAffiliateCodeView.as_view(),
        name="affiliate-resolve-code",
    ),

    # God Mode Affiliates
    path(
        "godmode/overview/",
        GodModeAffiliateOverviewView.as_view(),
        name="affiliate-godmode-overview",
    ),
    path(
        "godmode/affiliates/",
        GodModeAffiliateListCreateView.as_view(),
        name="affiliate-godmode-affiliates",
    ),
    path(
        "godmode/affiliates/<int:pk>/",
        GodModeAffiliateDetailView.as_view(),
        name="affiliate-godmode-affiliate-detail",
    ),
    path(
        "godmode/assign-business/",
        GodModeAssignBusinessView.as_view(),
        name="affiliate-godmode-assign-business",
    ),

    # God Mode Payouts
    path(
        "godmode/payout-batches/",
        GodModePayoutBatchListCreateView.as_view(),
        name="affiliate-godmode-payout-batches",
    ),
    path(
        "godmode/payout-batches/<int:pk>/mark-paid/",
        GodModePayoutBatchMarkPaidView.as_view(),
        name="affiliate-godmode-payout-batch-mark-paid",
    ),
]