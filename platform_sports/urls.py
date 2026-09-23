from rest_framework.routers import DefaultRouter

from .league_views import (
    LeagueDivisionViewSet,
    LeagueGameViewSet,
    LeagueRosterEntryViewSet,
    LeagueSeasonViewSet,
    LeagueTournamentViewSet,
    LeagueTeamEntryViewSet,
    SportsOrganizationMembershipViewSet,
    SportsOrganizationViewSet,
    SportsPlayerIdentityViewSet,
    SoftballRuleSetViewSet,
)
from .ops_views import (
    SoftballStatLedgerEntryViewSet,
    SportsPlayerProfileViewSet,
    SportsPlayerAwardViewSet,
    TeamFeeAssignmentViewSet,
    TeamFeeViewSet,
    TeamPaymentSettingsViewSet,
)
from .views import (
    SoftballPlateAppearanceViewSet,
    SportsGameViewSet,
    SportsGameBookPhotoViewSet,
    SportsPlayerViewSet,
    SportsTeamViewSet,
)

router = DefaultRouter()
router.register("teams", SportsTeamViewSet, basename="sports-teams")
router.register("players", SportsPlayerViewSet, basename="sports-players")
router.register("games", SportsGameViewSet, basename="sports-games")
router.register("game-book-photos", SportsGameBookPhotoViewSet, basename="sports-game-book-photos")
router.register("plate-appearances", SoftballPlateAppearanceViewSet, basename="sports-plate-appearances")
router.register("player-profiles", SportsPlayerProfileViewSet, basename="sports-player-profiles")
router.register("player-awards", SportsPlayerAwardViewSet, basename="sports-player-awards")
router.register("payment-settings", TeamPaymentSettingsViewSet, basename="sports-payment-settings")
router.register("team-fees", TeamFeeViewSet, basename="sports-team-fees")
router.register("fee-assignments", TeamFeeAssignmentViewSet, basename="sports-fee-assignments")
router.register("stat-ledger", SoftballStatLedgerEntryViewSet, basename="sports-stat-ledger")

router.register("organizations", SportsOrganizationViewSet, basename="sports-organizations")
router.register("organization-memberships", SportsOrganizationMembershipViewSet, basename="sports-organization-memberships")
router.register("seasons", LeagueSeasonViewSet, basename="sports-seasons")
router.register("divisions", LeagueDivisionViewSet, basename="sports-divisions")
router.register("league-teams", LeagueTeamEntryViewSet, basename="sports-league-teams")
router.register("league-games", LeagueGameViewSet, basename="sports-league-games")
router.register("tournaments", LeagueTournamentViewSet, basename="sports-tournaments")
router.register("league-rosters", LeagueRosterEntryViewSet, basename="sports-league-rosters")
router.register("player-identities", SportsPlayerIdentityViewSet, basename="sports-player-identities")
router.register("rule-sets", SoftballRuleSetViewSet, basename="sports-rule-sets")

urlpatterns = router.urls
