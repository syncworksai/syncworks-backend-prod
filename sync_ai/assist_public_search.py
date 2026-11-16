"""Optional public SERP search adapter, disabled by default.

Provider receives only the explicitly supplied public-search query. No source
URLs are fetched by the server; snippets are evidence of search results, NOT
independent verification of businesses, people, or their suitability.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import requests

ENDPOINT = "https://google.serper.dev/search"
MAX_RESULTS = 8


class ResearchDisabled(RuntimeError):
    pass


def public_search(query):
    if os.environ.get("SYNC_ASSIST_LIVE_RESEARCH_ENABLED") != "true":
        raise ResearchDisabled("Public research is disabled on this server.")
    key = os.environ.get("SERPER_API_KEY", "").strip()
    if not key:
        raise ResearchDisabled("Public research provider is not configured.")
    if not isinstance(query, str) or not 4 <= len(query.strip()) <= 120:
        raise ResearchDisabled("Public search query must be 4–120 characters.")

    # Fixed provider host, explicit timeout, no redirects, no requests to result URLs.
    try:
        response = requests.post(
            ENDPOINT,
            json={"q": query.strip(), "num": MAX_RESULTS},
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            timeout=(3, 7),
            allow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        raise ResearchDisabled("Search provider failed; no results were accepted.") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("organic"), list):
        raise ResearchDisabled("Search provider returned an invalid response.")
    results = []
    for item in payload["organic"][:MAX_RESULTS]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:180]
        link = str(item.get("link") or "").strip()[:500]
        snippet = str(item.get("snippet") or "").strip()[:450]
        url = urlparse(link)
        if not title or url.scheme != "https" or not url.hostname or url.username or url.password:
            continue
        # URL is only a reference, never fetched or called from here.
        results.append({
            "title": title, "website": link, "snippet": snippet,
            "provenance": "public_search_result_unverified", "source_provider": "serper",
            "contact_verified": False, "qualified": False,
        })
    return results
