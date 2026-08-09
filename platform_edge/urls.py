from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .live_views import live_mlb_board
from .views import PaperTradeViewSet, StrategyViewSet, dashboard, kalshi_connection, kalshi_verify

router = DefaultRouter()
router.register("strategies", StrategyViewSet, basename="edge-strategy")
router.register("paper-trades", PaperTradeViewSet, basename="edge-paper-trade")

urlpatterns = [
    path("dashboard/", dashboard, name="edge-dashboard"),
    path("live/mlb/", live_mlb_board, name="edge-live-mlb"),
    path("exchanges/kalshi/", kalshi_connection, name="edge-kalshi-connection"),
    path("exchanges/kalshi/verify/", kalshi_verify, name="edge-kalshi-verify"),
    path("", include(router.urls)),
]
