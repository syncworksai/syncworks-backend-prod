from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from django.conf import settings


def _graph_base() -> str:
    version = (getattr(settings, "META_GRAPH_API_VERSION", "v23.0") or "v23.0").strip()
    return f"https://graph.facebook.com/{version}"


def normalize_meta_error(error):
    if isinstance(error, dict):
        err = error.get("error") if isinstance(error.get("error"), dict) else error
        return {
            "message": str(err.get("message") or "Meta OAuth error"),
            "type": str(err.get("type") or "MetaOAuthError"),
            "code": err.get("code"),
            "subcode": err.get("error_subcode"),
        }
    return {"message": str(error or "Meta OAuth error"), "type": "MetaOAuthError", "code": None, "subcode": None}


def build_meta_authorization_url(state, redirect_uri):
    query = urlencode(
        {
            "client_id": getattr(settings, "META_APP_ID", ""),
            "redirect_uri": redirect_uri,
            "scope": ",".join(getattr(settings, "META_OAUTH_SCOPES", []) or []),
            "response_type": "code",
            "state": state,
        }
    )
    return f"https://www.facebook.com/{getattr(settings, 'META_GRAPH_API_VERSION', 'v23.0')}/dialog/oauth?{query}"


def _http_json(url: str, method: str = "GET", data: dict | None = None):
    payload = None
    headers = {"Accept": "application/json"}
    if data is not None:
        payload = urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = Request(url, data=payload, headers=headers, method=method)
    try:
        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        try:
            err_json = json.loads(body or "{}")
        except Exception:
            err_json = {"error": {"message": body or str(exc), "type": "HTTPError", "code": exc.code}}
        raise ValueError(normalize_meta_error(err_json))


def exchange_code_for_token(code, redirect_uri):
    data = {
        "client_id": getattr(settings, "META_APP_ID", ""),
        "client_secret": getattr(settings, "META_APP_SECRET", ""),
        "redirect_uri": redirect_uri,
        "code": code,
    }
    token_url = f"{_graph_base()}/oauth/access_token"
    response = _http_json(token_url, method="GET", data=data)
    if "error" in response:
        raise ValueError(normalize_meta_error(response))
    return response


def fetch_meta_account_metadata(access_token):
    me_url = f"{_graph_base()}/me?{urlencode({'fields': 'id,name', 'access_token': access_token})}"
    me_data = _http_json(me_url)
    if "error" in me_data:
        raise ValueError(normalize_meta_error(me_data))
    return {
        "id": str(me_data.get("id") or ""),
        "name": str(me_data.get("name") or ""),
    }
