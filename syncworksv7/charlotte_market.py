import os
import re
from datetime import date
import requests
from django.core.cache import cache
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def daily_history(request):
    allowed = os.environ.get("CHARLOTTE_PILOT_EMAIL", "").strip().lower()
    if not allowed or request.user.email.strip().lower() != allowed:
        return Response({"detail": "Pilot unavailable."}, status=403)
    symbol = request.query_params.get("symbol", "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", symbol):
        return Response({"detail": "Invalid symbol."}, status=400)
    key = os.environ.get("CHARLOTTE_TWELVEDATA_KEY", "").strip()
    if not key:
        return Response({"detail": "Market data provider not configured."}, status=503)
    cache_key = "charlotte:daily:v1:" + symbol
    result = cache.get(cache_key)
    if result is not None:
        return Response(result)
    try:
        response = requests.get("https://api.twelvedata.com/time_series", params={"symbol": symbol, "interval": "1day", "outputsize": 250, "apikey": key}, timeout=10)
        response.raise_for_status()
        payload = response.json()
        rows = []
        for row in payload["values"]:
            day = date.fromisoformat(row["datetime"])
            if day >= date.today():
                continue
            close = float(row["close"])
            if not 0 < close < float("inf"):
                raise ValueError("Invalid price")
            rows.append({"date": day.isoformat(), "close": close})
        rows.sort(key=lambda row: row["date"])
        if not rows or len({row["date"] for row in rows}) != len(rows):
            raise ValueError("Invalid history")
        result = {"symbol": symbol, "source": "Twelve Data", "interval": "1day", "as_of": rows[-1]["date"], "historical_only": True, "adjustment": "provider basis; not independently verified", "bars": rows}
    except (requests.RequestException, ValueError, KeyError, TypeError, OverflowError):
        return Response({"detail": "Historical market data unavailable."}, status=503)
    cache.set(cache_key, result, 900)
    return Response(result)
