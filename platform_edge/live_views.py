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


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def live_mlb_board(request):
    target_date = request.query_params.get("date") or None
    return Response(get_mlb_research_board(target_date, _minimum_edge(request, 8.0)))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def live_nfl_board(request):
    target_date = request.query_params.get("date") or None
    return Response(get_football_board("NFL", target_date, _minimum_edge(request, 5.0)))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def live_ncaaf_board(request):
    target_date = request.query_params.get("date") or None
    return Response(get_football_board("NCAAF", target_date, _minimum_edge(request, 5.0)))
