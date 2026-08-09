from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PaperTradeViewSet, StrategyViewSet, dashboard, kalshi_connection

router = DefaultRouter()
router.register("strategies", StrategyViewSet, basename="edge-strategy")
router.register("paper-trades", PaperTradeViewSet, basename="edge-paper-trade")

urlpatterns = [
    path("dashboard/", dashboard, name="edge-dashboard"),
    path("exchanges/kalshi/", kalshi_connection, name="edge-kalshi-connection"),
    path("", include(router.urls)),
]
