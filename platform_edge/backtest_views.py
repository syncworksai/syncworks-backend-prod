from datetime import datetime, time

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .backtest import run_mlb_backtest


def _date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mlb_backtest(request):
    start_date = _date(request.query_params.get("start"))
    end_date = _date(request.query_params.get("end"))
    if not start_date and not end_date:
        result = run_mlb_backtest()
    else:
        start = timezone.make_aware(datetime.combine(start_date or end_date, time.min))
        end = timezone.make_aware(datetime.combine(end_date or start_date, time.max))
        result = run_mlb_backtest(start, end, fee_bps=max(0.0, min(500.0, float(request.query_params.get("fee_bps") or 0))), risk_cents=max(1, min(100000, int(request.query_params.get("risk_cents") or 100))))
    return Response(result)
