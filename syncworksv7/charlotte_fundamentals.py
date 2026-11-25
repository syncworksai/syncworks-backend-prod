import os
import re
import math
from datetime import date
import requests
from django.core.cache import cache
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

def annual_fact(facts, tags, unit):
    for tag in tags:
        rows = facts.get(tag, {}).get("units", {}).get(unit, [])
        valid = []
        for row in rows:
            try:
                start, end, filed = (date.fromisoformat(row[k]) for k in ("start", "end", "filed"))
                if row.get("form") not in ("10-K", "10-K/A") or not 330 <= (end-start).days <= 380 or not end <= filed <= date.today():
                    continue
                if not math.isfinite(float(row["val"])) or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", row["accn"]):
                    continue
                valid.append(row)
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        if valid:
            r = max(valid, key=lambda x: (x["end"], x["filed"]))
            return {"value": r["val"], "unit": unit, "period_start": r["start"], "period_end": r["end"], "filed": r["filed"], "accession": r["accn"], "tag": tag}
    return None

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def fundamentals(request):
    allowed = os.environ.get("CHARLOTTE_PILOT_EMAIL", "").strip().lower()
    if not allowed or str(request.user.email or "").strip().lower() != allowed:
        return Response({"detail": "Pilot unavailable."}, status=403)
    symbol = request.query_params.get("symbol", "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", symbol):
        return Response({"detail": "Invalid symbol."}, status=400)
    agent = os.environ.get("CHARLOTTE_SEC_USER_AGENT", "").strip()
    if not agent:
        return Response({"detail": "SEC contact configuration required."}, status=503)
    key = "charlotte:sec:annual:v1:" + symbol
    result = cache.get(key)
    if result is not None:
        return Response(result)
    headers = {"User-Agent": agent, "Accept": "application/json"}
    try:
        tickers = cache.get("charlotte:sec:tickers:v1")
        if tickers is None:
            r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=6)
            r.raise_for_status()
            tickers = r.json()
            cache.set("charlotte:sec:tickers:v1", tickers, 86400)
        match = next((v for v in tickers.values() if v["ticker"].upper() == symbol.replace(".", "-")), None)
        if not match:
            return Response({"detail": "No SEC ticker match."}, status=404)
        cik = int(match["cik_str"])
        r = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", headers=headers, timeout=7)
        r.raise_for_status()
        payload = r.json()
        facts = payload.get("facts", {}).get("us-gaap", {})
        metrics = {
            "annual_diluted_eps": annual_fact(facts, ["EarningsPerShareDiluted"], "USD/shares"),
            "annual_revenue": annual_fact(facts, ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"], "USD"),
            "annual_net_income": annual_fact(facts, ["NetIncomeLoss"], "USD"),
            "annual_operating_cash_flow": annual_fact(facts, ["NetCashProvidedByUsedInOperatingActivities"], "USD"),
        }
        for fact in metrics.values():
            if fact:
                fact["filing_url"] = f"https://www.sec.gov/Archives/edgar/data/{cik}/{fact['accession'].replace('-', '')}/"
        result = {"symbol": symbol, "company": match["title"], "source": "SEC EDGAR", "basis": "Annual US GAAP filings; not trailing twelve months or analyst estimates", "metrics": metrics}
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return Response({"detail": "SEC fundamentals unavailable."}, status=503)
    cache.set(key, result, 3600)
    return Response(result)
