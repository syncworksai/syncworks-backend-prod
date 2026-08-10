from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .research_model import get_mlb_research_board


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def live_mlb_board(request):
    target_date = request.query_params.get("date") or None
    try:
        minimum_edge = float(request.query_params.get("minimum_edge") or 8)
    except (TypeError, ValueError):
        minimum_edge = 8.0
    minimum_edge = max(0.0, min(50.0, minimum_edge))
    return Response(get_mlb_research_board(target_date, minimum_edge))
