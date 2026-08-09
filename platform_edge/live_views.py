from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .live_data import get_live_mlb_board


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def live_mlb_board(request):
    target_date = request.query_params.get("date") or None
    return Response(get_live_mlb_board(target_date))
