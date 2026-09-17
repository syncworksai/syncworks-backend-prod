from rest_framework.routers import DefaultRouter

from .league_views import (
    LeagueDivisionViewSet,
    LeagueRosterEntryViewSet,
    LeagueSeasonViewSet,
    LeagueTeamEntryViewSet,
    SportsOrganizationMembershipViewSet,
    SportsOrganizationViewSet,
    SportsPlayerIdentityViewSet,
)
from .views import (
    SoftballPlateAppearanceViewSet,
    SportsGameViewSet,
    SportsPlayerViewSet,
    SportsTeamViewSet,
)

router = DefaultRouter()
router.register("teams", SportsTeamViewSet, basename="sports-teams")
router.register("players", SportsPlayerViewSet, basename="sports-players")
router.register("games", SportsGameViewSet, basename="sports-games")
router.register("plate-appearances", SoftballPlateAppearanceViewSet, basename="sports-plate-appearances")

router.register("organizations", SportsOrganizationViewSet, basename="sports-organizations")
router.register("organization-memberships", SportsOrganizationMembershipViewSet, basename="sports-organization-memberships")
router.register("seasons", LeagueSeasonViewSet, basename="sports-seasons")
router.register("divisions", LeagueDivisionViewSet, basename="sports-divisions")
router.register("league-teams", LeagueTeamEntryViewSet, basename="sports-league-teams")
router.register("league-rosters", LeagueRosterEntryViewSet, basename="sports-league-rosters")
router.register("player-identities", SportsPlayerIdentityViewSet, basename="sports-player-identities")

urlpatterns = router.urls
