from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .live_data import get_live_mlb_board
from .models import EdgeStrategy
from .strategy_v2 import V2_VERSION, run_v2_for_user, strategy_v2_scoreboard


def _eligible_users():
    ids = EdgeStrategy.objects.values_list("user_id", flat=True).distinct()
    return get_user_model().objects.filter(id__in=ids, is_active=True)


@api_view(["POST"])
@permission_classes([AllowAny])
def system_strategy_v2_tick(request):
    """Paper-only scheduler endpoint for Strategy Engine v2. No exchange-order path exists here."""
    board = get_live_mlb_board()
    results = []
    for user in _eligible_users():
        try:
            results.append(run_v2_for_user(user, board=board))
        except Exception as exc:
            results.append({"error": True, "detail": str(exc)[:160]})
    return Response({
        "mode": "paper_only",
        "live_money_enabled": False,
        "version": V2_VERSION,
        "ran_at": timezone.now(),
        "users_processed": len(results),
        "opened_count": sum(row.get("opened_count", 0) for row in results),
        "managed_count": sum(row.get("managed_count", 0) for row in results),
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def strategy_v2_tick_me(request):
    board = get_live_mlb_board()
    result = run_v2_for_user(request.user, board=board)
    return Response({
        "mode": "paper_only",
        "live_money_enabled": False,
        "version": V2_VERSION,
        "ran_at": timezone.now(),
        **result,
    })
