"""Amazon Creators API integration. Credentials must only be supplied by server environment."""
import os
import requests
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import UserRateThrottle

TAG = "syncworksapp-20"

class ShoppingSearchThrottle(UserRateThrottle):
    scope = "shop_search"
    rate = "10/min"

def _text(value):
    return str(value or "").strip()

@api_view(["GET"])
@permission_classes([IsAuthenticated])
@throttle_classes([ShoppingSearchThrottle])
def search_products(request):
    q = _text(request.query_params.get("q"))
    try:
        low = float(request.query_params.get("min") or 0)
        high = float(request.query_params.get("max") or 50)
    except (ValueError, TypeError):
        return JsonResponse({"error": "Invalid price range"}, status=400)
    priority = _text(request.query_params.get("priority")) or "value"
    if not 2 <= len(q) <= 180 or not 0 <= low < high <= 10000 or priority not in ("quality", "value", "budget"):
        return JsonResponse({"error": "Invalid search parameters"}, status=400)
    client_id = os.environ.get("AMAZON_CREATORS_CLIENT_ID")
    secret = os.environ.get("AMAZON_CREATORS_CLIENT_SECRET")
    if not client_id or not secret:
        return JsonResponse({"configured": False, "items": [], "message": "Amazon Creators API credentials are not configured."}, status=503)
    try:
        auth = requests.post("https://api.amazon.com/auth/o2/token", json={
            "grant_type": "client_credentials", "client_id": client_id,
            "client_secret": secret, "scope": "creatorsapi::default"
        }, timeout=8)
        auth.raise_for_status()
        token = auth.json()["access_token"]
        payload = {
            "keywords": q, "searchIndex": "All", "itemCount": 10,
            "marketplace": "www.amazon.com", "partnerTag": TAG,
            "minPrice": int(round(low * 100)), "maxPrice": int(round(high * 100)),
            "resources": ["itemInfo.title", "images.primary.medium", "offersV2.listings.price"]
        }
        if priority == "budget":
            payload["sortBy"] = "Price:LowToHigh"
        resp = requests.post("https://creatorsapi.amazon/catalog/v1/searchItems",
            json=payload, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
            "x-marketplace": "www.amazon.com"}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError, KeyError):
        return JsonResponse({"items": [], "message": "Amazon catalog is temporarily unavailable."}, status=502)
    candidates = []
    for item in (data.get("searchResult") or {}).get("items", []):
        title = ((item.get("itemInfo") or {}).get("title") or {}).get("displayValue")
        url = item.get("detailPageURL") or ""
        if not title or not url.startswith("https://www.amazon.com/"):
            continue
        offers = ((item.get("offersV2") or {}).get("listings") or [])
        price = (((offers[0] or {}).get("price") or {}).get("money") or {}).get("amount") if offers else None
        if price is None:  # Never claim to enforce a budget without an actual price.
            continue
        try:
            price = float(price)
        except (ValueError, TypeError):
            continue
        if price < low or price > high:
            continue
        image = (((item.get("images") or {}).get("primary") or {}).get("medium") or {}).get("url")
        candidates.append({"title": title, "price": price, "image": image, "url": url, "asin": item.get("asin")})
    if priority == "budget":
        candidates.sort(key=lambda x: x["price"])
    # Amazon does not always return verified review scores. No invented rating claims.
    return JsonResponse({"configured": True, "items": candidates[:3], "priority": priority})
