from datetime import date, timedelta

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .backtest import run_mlb_backtest


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mlb_backtest(request):
    today = date.today()
    try:
        days = int(request.query_params.get("days") or 14)
        max_games = int(request.query_params.get("max_games") or 100)
    except (TypeError, ValueError):
        return Response({"detail": "days and max_games must be integers."}, status=400)
    days = max(1, min(60, days))
    max_games = max(1, min(500, max_games))
    start = today - timedelta(days=days)
    return Response(run_mlb_backtest(start, today, max_games=max_games))
