import os
import math
from datetime import date
from concurrent.futures import ThreadPoolExecutor
import requests
from django.core.cache import cache
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

SERIES = {
    "DGS10": ("10-year Treasury yield", "percent", "Higher yields may increase borrowing costs and pressure valuations."),
    "FEDFUNDS": ("Federal funds rate", "percent", "Higher policy rates generally make borrowing more expensive."),
    "UNRATE": ("Unemployment rate", "percent", "Rising unemployment may weaken household spending."),
    "CPIAUCSL": ("Consumer price index", "index", "Changes in the price index describe inflation; the index itself is not an inflation rate."),
    "DRCCLACBS": ("Credit card delinquency rate", "percent", "Rising delinquencies may indicate household financial strain."),
    "REVOLSL": ("Revolving consumer credit", "millions of USD", "Growth may reflect stronger spending or increased dependence on debt."),
    "PCE": ("Personal consumption expenditures", "billions of USD, annual rate", "Spending supports company revenues, but nominal growth also reflects prices."),
    "GDPC1": ("Real GDP", "billions of chained USD, annual rate", "Real output growth measures economic activity after inflation."),
}

def observations(rows):
    result = {}
    for row in rows:
        try:
            day = date.fromisoformat(row["date"])
            value = float(row["value"])
            if day <= date.today() and math.isfinite(value):
                result[day.isoformat()] = value
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    return [{"date": k, "value": result[k]} for k in sorted(result)]

def fetch_series(item, key):
    sid, (label, unit, explanation) = item
    result = {"id": sid, "label": label, "unit": unit, "explanation": explanation, "source_url": "https://fred.stlouisfed.org/series/" + sid, "observations": []}
    try:
        r = requests.get("https://api.stlouisfed.org/fred/series/observations", params={"series_id": sid, "api_key": key, "file_type": "json", "sort_order": "desc", "limit": 24}, timeout=5)
        r.raise_for_status()
        result["observations"] = observations(r.json()["observations"])
    except (requests.RequestException, ValueError, TypeError, KeyError):
        pass
    return result

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def macro(request):
    allowed = os.environ.get("CHARLOTTE_PILOT_EMAIL", "").strip().lower()
    if not allowed or str(request.user.email or "").strip().lower() != allowed:
        return Response({"detail": "Pilot unavailable."}, status=403)
    key = os.environ.get("CHARLOTTE_FRED_KEY", "").strip()
    if not key:
        return Response({"detail": "FRED data provider not configured."}, status=503)
    cached = cache.get("charlotte:macro:v1")
    if cached is not None:
        return Response(cached)
    with ThreadPoolExecutor(max_workers=4) as pool:
        series = list(pool.map(lambda item: fetch_series(item, key), SERIES.items()))
    if not any(s["observations"] for s in series):
        return Response({"detail": "Economic data unavailable."}, status=503)
    result = {"source": "FRED", "retrieved_on": date.today().isoformat(), "series": series, "note": "Observation dates are not release dates. Data may be revised; association does not establish causation."}
    cache.set("charlotte:macro:v1", result, 3600 if all(s["observations"] for s in series) else 120)
    return Response(result)
