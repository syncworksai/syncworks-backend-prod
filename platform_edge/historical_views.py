from datetime import date

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .historical_sync import summarize_replay, sync_mlb_kalshi_day


def _target_date(raw: str | None) -> date:
    if not raw:
        return date.today()
    return date.fromisoformat(raw)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def sync_mlb_kalshi(request):
    try:
        target = _target_date(request.data.get("date"))
        max_games = max(1, min(15, int(request.data.get("max_games") or 15)))
    except (TypeError, ValueError):
        return Response({"detail": "Use date=YYYY-MM-DD and max_games as an integer."}, status=400)
    return Response(sync_mlb_kalshi_day(target, max_games=max_games))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def replay_summary(request):
    try:
        target = _target_date(request.query_params.get("date"))
        minimum_edge = float(request.query_params.get("minimum_edge") or 8)
    except (TypeError, ValueError):
        return Response({"detail": "Use date=YYYY-MM-DD and minimum_edge as a number."}, status=400)
    minimum_edge = max(0.0, min(50.0, minimum_edge))
    return Response(summarize_replay(target, minimum_edge))
