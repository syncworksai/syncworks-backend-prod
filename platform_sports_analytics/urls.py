from django.urls import path

from .views import (
    AdvancedTeamStatsView,
    GameCastPreviewView,
    GameCastSettingsView,
    PlayContextUpsertView,
    PlayerSprayView,
    PlayerCardView,
    PublicGameCastView,
)

urlpatterns = [
    path("advanced/play-context/", PlayContextUpsertView.as_view(), name="sports-advanced-play-context"),
    path("advanced/teams/<int:team_id>/stats/", AdvancedTeamStatsView.as_view(), name="sports-advanced-team-stats"),
    path("advanced/players/<int:player_id>/spray/", PlayerSprayView.as_view(), name="sports-player-spray"),
    path("advanced/players/<int:player_id>/card/", PlayerCardView.as_view(), name="sports-player-card"),
    path("advanced/games/<int:game_id>/gamecast/", GameCastSettingsView.as_view(), name="sports-gamecast-settings"),
    path("gamecast/<uuid:token>/preview/", GameCastPreviewView.as_view(), name="sports-gamecast-preview"),
    path("gamecast/<uuid:token>/", PublicGameCastView.as_view(), name="sports-public-gamecast"),
]
