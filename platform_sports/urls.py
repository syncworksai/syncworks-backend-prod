from rest_framework.routers import DefaultRouter

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

urlpatterns = router.urls
