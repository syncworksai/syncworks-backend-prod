import os
from urllib.parse import urlencode

import requests

SCOPES = "openid email profile offline_access User.Read Calendars.ReadWrite"


def tenant():
    return (os.getenv("MICROSOFT_CALENDAR_TENANT") or "common").strip()


def redirect_uri():
    base = (os.getenv("CALENDAR_OAUTH_BASE_URL") or "https://api.syncworksapp.com").rstrip("/")
    return f"{base}/api/v1/personal-calendar/connections/oauth/microsoft/callback/"


def authorization_url(state):
    client_id = (os.getenv("MICROSOFT_CALENDAR_CLIENT_ID") or "").strip()
    if not client_id:
        raise RuntimeError("Microsoft Calendar OAuth is not configured.")
    query = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "response_mode": "query",
        "scope": SCOPES,
        "state": state,
    })
    return f"https://login.microsoftonline.com/{tenant()}/oauth2/v2.0/authorize?{query}"


def exchange_code(code):
    response = requests.post(
        f"https://login.microsoftonline.com/{tenant()}/oauth2/v2.0/token",
        data={
            "client_id": os.getenv("MICROSOFT_CALENDAR_CLIENT_ID"),
            "client_secret": os.getenv("MICROSOFT_CALENDAR_CLIENT_SECRET"),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri(),
            "scope": SCOPES,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def profile(access_token):
    response = requests.get(
        "https://graph.microsoft.com/v1.0/me?$select=id,displayName,mail,userPrincipalName",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return {
        "id": data.get("id"),
        "email": data.get("mail") or data.get("userPrincipalName") or "",
        "name": data.get("displayName", ""),
    }


def calendars(access_token):
    response = requests.get(
        "https://graph.microsoft.com/v1.0/me/calendars?$select=id,name,color,canEdit,isDefaultCalendar",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("value") or []
