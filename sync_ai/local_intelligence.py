from __future__ import annotations

import re

from user_accounts.views.context_router import resolve_location_context
from user_accounts.views.local_discovery import CATEGORY_QUERIES, reverse_geocode, search_places

LOCAL_HINTS = (
    "near me", "nearby", "around me", "around here", "close to me", "closest",
    "where can i", "where should i", "find me", "find a", "find an", "find somewhere",
    "restaurant", "eat", "food", "lunch", "dinner", "breakfast", "coffee", "pizza", "sushi",
    "buy", "shop", "store", "retail", "sporting goods", "grocery",
    "barber", "salon", "mechanic", "service", "repair",
    "things to do", "something to do", "playground", "park", "museum", "activity", "activities",
)


def infer_local_intent(message: str) -> dict | None:
    text = re.sub(r"\s+", " ", str(message or "").strip()).lower()
    if not text or not any(hint in text for hint in LOCAL_HINTS):
        return None

    if any(word in text for word in ("eat", "food", "restaurant", "lunch", "dinner", "breakfast", "coffee", "pizza", "sushi")):
        category = "FOOD"
    elif any(word in text for word in ("buy", "shop", "store", "retail", "sporting goods", "grocery")):
        category = "RETAIL"
    elif any(word in text for word in ("barber", "salon", "mechanic", "service", "repair")):
        category = "SERVICES"
    elif any(word in text for word in ("things to do", "something to do", "playground", "park", "museum", "activity", "activities")):
        category = "EVENTS"
    else:
        category = "NEARBY"

    query = text
    for phrase in ("sync", "please", "near me", "nearby", "around me", "around here", "close to me", "find me", "find", "where can i", "where should i"):
        query = query.replace(phrase, " ")
    query = re.sub(r"\b(can you|could you|i need|i want|somewhere|something|a place|places|to go|for me)\b", " ", query)
    query = re.sub(r"\s+", " ", query).strip(" ?.,")
    if not query:
        query = CATEGORY_QUERIES[category]
    return {"category": category, "query": query, "original": text}


def _location_label(context: dict) -> str:
    location = context.get("location") or {}
    return location.get("formatted_address") or location.get("label") or location.get("city") or "your selected area"


def build_local_response(*, user, message: str, data: dict) -> dict | None:
    intent = infer_local_intent(message)
    if not intent:
        return None

    category = intent["category"]
    context = resolve_location_context(user, category, data)
    location = context.get("location")
    if not location:
        return {
            "message": "I can search nearby, but I need a location first. Allow Current Location or add a Home address in Settings.",
            "local_discovery": {"available": False, "reason": "LOCATION_REQUIRED", "category": category, "query": intent["query"], "context": context, "results": []},
        }

    if context.get("source") == "CURRENT" and location.get("latitude") is not None and location.get("longitude") is not None:
        resolved = reverse_geocode(location["latitude"], location["longitude"])
        if resolved.get("available"):
            location = {**location, **resolved}
            context["location"] = location

    result = search_places(intent["query"], location, data.get("radius_meters") or 12000)
    results = result.get("results") or []
    source_label = "your current location" if context.get("source") == "CURRENT" else "your Home location"

    if not result.get("available"):
        message_text = "I understood the nearby search, but live place results are not available right now."
    elif not results:
        message_text = f"I searched near {_location_label(context)} using {source_label}, but I did not find a strong match for {intent['query']}. Try a broader search."
    else:
        names = [row.get("name") for row in results[:3] if row.get("name")]
        message_text = f"I found {len(results)} nearby matches using {source_label}. Top options: " + ", ".join(names) + ". Open the results below for addresses and ratings."

    return {
        "message": message_text,
        "local_discovery": {
            **result,
            "category": category,
            "query": intent["query"],
            "context": context,
            "location": location,
            "privacy": {"current_location_persisted": False, "home_overwritten": False},
        },
    }
