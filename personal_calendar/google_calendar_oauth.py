import os
from urllib.parse import urlencode

import requests


SCOPES = "openid email profile https://www.googleapis.com/auth/calendar"


def redirect_uri():
    base = (os.getenv("CALENDAR_OAUTH_BASE_URL") or "https://api.syncworksapp.com").rstrip("/")
    return f"{base}/api/v1/personal-calendar/connections/oauth/google/callback/"


def authorization_url(state):
    client_id = (os.getenv("GOOGLE_CALENDAR_CLIENT_ID") or "").strip()
    if not client_id:
        raise RuntimeError("Google Calendar OAuth is not configured.")
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })


def exchange_code(code):
    response = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.getenv("GOOGLE_CALENDAR_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET"),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri(),
    }, timeout=30)
    response.raise_for_status()
    return response.json()


def profile(access_token):
    response = requests.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    response.raise_for_status()
    data = response.json()
    return {"id": data.get("sub"), "email": data.get("email", ""), "name": data.get("name", "")}


def calendars(access_token):
    response = requests.get("https://www.googleapis.com/calendar/v3/users/me/calendarList", headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    response.raise_for_status()
    return response.json().get("items") or []
