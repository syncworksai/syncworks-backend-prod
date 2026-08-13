from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .backtest_views import mlb_backtest
from .historical_views import replay_summary, sync_mlb_kalshi
from .live_views import live_mlb_board
from .portfolio_views import portfolio_live, portfolio_paper_tick
from .research_views import mlb_research_board, paper_simulate, paper_summary
from .server_paper import server_paper_status, system_paper_tick
from .strategy_a_views import strategy_a_live, strategy_a_paper_tick
from .strategy_scoreboard import strategy_scoreboard
from .views import PaperTradeViewSet, StrategyViewSet, dashboard, kalshi_connection, kalshi_verify

router = DefaultRouter()
router.register("strategies", StrategyViewSet, basename="edge-strategy")
router.register("paper-trades", PaperTradeViewSet, basename="edge-paper-trade")

urlpatterns = [
    path("dashboard/", dashboard, name="edge-dashboard"),
    path("live/mlb/", live_mlb_board, name="edge-live-mlb"),
    path("strategy-a/live/", strategy_a_live, name="edge-strategy-a-live"),
    path("strategy-a/paper/tick/", strategy_a_paper_tick, name="edge-strategy-a-paper-tick"),
    path("portfolio/live/", portfolio_live, name="edge-portfolio-live"),
    path("portfolio/paper/tick/", portfolio_paper_tick, name="edge-portfolio-paper-tick"),
    path("portfolio/server/status/", server_paper_status, name="edge-server-paper-status"),
    path("portfolio/strategies/scoreboard/", strategy_scoreboard, name="edge-strategy-scoreboard"),
    path("system/paper/tick/", system_paper_tick, name="edge-system-paper-tick"),
    path("research/mlb/", mlb_research_board, name="edge-research-mlb"),
    path("research/mlb/backtest/", mlb_backtest, name="edge-research-mlb-backtest"),
    path("research/mlb/history/sync/", sync_mlb_kalshi, name="edge-research-mlb-history-sync"),
    path("research/mlb/history/summary/", replay_summary, name="edge-research-mlb-history-summary"),
    path("research/paper/simulate/", paper_simulate, name="edge-paper-simulate"),
    path("research/paper/summary/", paper_summary, name="edge-paper-summary"),
    path("exchanges/kalshi/", kalshi_connection, name="edge-kalshi-connection"),
    path("exchanges/kalshi/verify/", kalshi_verify, name="edge-kalshi-verify"),
    path("", include(router.urls)),
]
