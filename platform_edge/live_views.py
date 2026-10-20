from datetime import timedelta

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .football import get_football_board
from .research_model import get_mlb_research_board


def _minimum_edge(request, default=8.0):
    try:
        value = float(request.query_params.get("minimum_edge") or default)
    except (TypeError, ValueError):
        value = default
    return max(0.0, min(50.0, value))


def _football_board(request, sport: str, default_edge: float, lookahead_days: int = 4):
    """Load an exact ESPN scoreboard date instead of the rejected range format.

    If the caller did not choose a date, walk forward until the next slate with
    games is found. This keeps Saturday NFL and mid-week college views useful
    without sending ESPN an unsupported YYYYMMDD-YYYYMMDD range.
    """
    explicit_date = request.query_params.get("date") or None
    minimum_edge = _minimum_edge(request, default_edge)
    if explicit_date:
        board = get_football_board(sport, explicit_date, minimum_edge)
        board["slate_date"] = explicit_date
        board["slate_is_upcoming"] = False
        board["days_ahead"] = 0
        return board

    start = timezone.localdate()
    last_board = None
    for days_ahead in range(max(0, lookahead_days) + 1):
        slate_date = (start + timedelta(days=days_ahead)).isoformat()
        board = get_football_board(sport, slate_date, minimum_edge)
        board["slate_date"] = slate_date
        board["slate_is_upcoming"] = days_ahead > 0
        board["days_ahead"] = days_ahead
        last_board = board
        if board.get("games"):
            return board

    return last_board or {
        "sport": sport,
        "games": [],
        "signals": [],
        "slate_date": start.isoformat(),
        "slate_is_upcoming": False,
        "days_ahead": 0,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def live_mlb_board(request):
    target_date = request.query_params.get("date") or None
    return Response(get_mlb_research_board(target_date, _minimum_edge(request, 8.0)))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def live_nfl_board(request):
    return Response(_football_board(request, "NFL", 5.0, lookahead_days=4))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def live_ncaaf_board(request):
    return Response(_football_board(request, "NCAAF", 5.0, lookahead_days=4))
