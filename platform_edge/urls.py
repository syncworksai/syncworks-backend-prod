from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .backtest_views import mlb_backtest
from .live_views import live_mlb_board
from .research_views import mlb_research_board, paper_simulate, paper_summary
from .views import PaperTradeViewSet, StrategyViewSet, dashboard, kalshi_connection, kalshi_verify

router = DefaultRouter()
router.register("strategies", StrategyViewSet, basename="edge-strategy")
router.register("paper-trades", PaperTradeViewSet, basename="edge-paper-trade")

urlpatterns = [
    path("dashboard/", dashboard, name="edge-dashboard"),
    path("live/mlb/", live_mlb_board, name="edge-live-mlb"),
    path("research/mlb/", mlb_research_board, name="edge-research-mlb"),
    path("research/mlb/backtest/", mlb_backtest, name="edge-research-mlb-backtest"),
    path("research/paper/simulate/", paper_simulate, name="edge-paper-simulate"),
    path("research/paper/summary/", paper_summary, name="edge-paper-summary"),
    path("exchanges/kalshi/", kalshi_connection, name="edge-kalshi-connection"),
    path("exchanges/kalshi/verify/", kalshi_verify, name="edge-kalshi-verify"),
    path("", include(router.urls)),
]
