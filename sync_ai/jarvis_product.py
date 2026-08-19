from __future__ import annotations

import os
from copy import deepcopy

from django.db.models import Q
from django.utils import timezone

from user_accounts.models import Business, BusinessMember, CustomerSettings, PMProperty, UserBillingProfile

TEST_EMAILS = {"jacoblord7@outlook.com"}

DEFAULT_LIVE = {
    "enabled": True,
    "weather_enabled": True,
    "weather_alerts": True,
    "travel_weather": True,
    "news_mode": "MAJOR_ONLY",
    "news_topics": [],
    "sports": [],
    "arrival_buffer_minutes": 15,
    "departure_reminder_minutes": 10,
}

DEFAULT_PROFILE = {
    "assistant_name": "SYNC",
    "tone": "CALM",
    "briefing_length": "STANDARD",
    "template": "GENERAL",
    "timezone": "",
    "wake_time": "07:00",
    "bedtime": "22:30",
    "quiet_hours_enabled": False,
    "goals": ["ORGANIZE_DAY", "FIND_LOCAL_SERVICES"],
    "modules": {},
    "permissions": {"view": True, "prepare": True, "confirm": True, "automate": False},
    "home_location": {"label": "", "latitude": None, "longitude": None},
    "live": DEFAULT_LIVE,
    "todos": [],
    "onboarding_step": 0,
    "onboarding_complete": False,
    "plan": "BASIC",
}

PLANS = [
    {"id": "BASIC", "name": "Basic", "price": 0, "description": "Marketplace search, service requests, manual schedule and tasks, and a limited briefing."},
    {"id": "PERSONAL", "name": "Personal AI", "price": 12.99, "description": "Voice briefings, weather and travel intelligence, calendar intelligence, Health, Money, and email intelligence as connections are enabled."},
    {"id": "FAMILY", "name": "Family", "price": 22.99, "description": "Personal AI plus shared schedules, household coordination, family alerts, weather and travel intelligence."},
    {"id": "EXECUTIVE", "name": "Executive", "price": 34.99, "description": "Multiple businesses, rental properties, affiliates, deeper reports, weather/travel intelligence, and approved actions."},
]


def _deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def is_test_access(user) -> bool:
    configured = {item.strip().lower() for item in (os.getenv("SYNC_ASSISTANT_TEST_EMAILS") or os.getenv("SYNC_JARVIS_TEST_EMAILS") or "").split(",") if item.strip()}
    return (user.email or "").strip().lower() in (TEST_EMAILS | configured)


def settings_for(user):
    return CustomerSettings.objects.get_or_create(user=user)[0]


def load_profile(user) -> tuple[CustomerSettings, dict]:
    settings = settings_for(user)
    root = deepcopy(settings.finance_profile or {})
    stored = root.get("sync_assistant") or root.get("jarvis") or {}
    return settings, _deep_merge(DEFAULT_PROFILE, stored)


def save_profile(user, updates: dict) -> dict:
    settings, profile = load_profile(user)
    allowed = set(DEFAULT_PROFILE)
    for key, value in updates.items():
        if key in allowed:
            if isinstance(DEFAULT_PROFILE.get(key), dict) and isinstance(value, dict):
                profile[key] = _deep_merge(profile.get(key) or {}, value)
            else:
                profile[key] = value
    root = deepcopy(settings.finance_profile or {})
    root["sync_assistant"] = profile
    root.pop("jarvis", None)
    settings.finance_profile = root
    settings.save(update_fields=("finance_profile", "updated_at"))
    return profile


def effective_plan(user, profile: dict) -> str:
    return "EXECUTIVE" if is_test_access(user) else str(profile.get("plan") or "BASIC").upper()


def live_access(user, profile: dict) -> bool:
    """Weather, traffic, sports and future news are included in paid Assistant plans."""
    return is_test_access(user) or effective_plan(user, profile) in {"PERSONAL", "FAMILY", "EXECUTIVE"}


def entitlements(user, profile: dict) -> dict:
    plan = effective_plan(user, profile)
    paid = plan != "BASIC"
    live = live_access(user, profile)
    return {
        "plan": plan,
        "test_access": is_test_access(user),
        "voice": paid,
        "overnight_briefing": paid,
        "email_intelligence": paid,
        "calendar_intelligence": paid,
        "health": paid,
        "money": paid,
        "business": paid,
        "property_management": plan == "EXECUTIVE",
        "family": plan in {"FAMILY", "EXECUTIVE"},
        "approved_actions": paid,
        "weather_intelligence": live,
        "travel_intelligence": live,
        "news_intelligence": live,
        "sports_intelligence": live,
        # Compatibility key for clients released before Live was folded into plans.
        "sync_assistant_live": live,
    }


def _businesses_for(user):
    member_ids = BusinessMember.objects.filter(user=user, is_active=True).values_list("business_id", flat=True)
    return Business.objects.filter(Q(owner=user) | Q(id__in=member_ids), is_active=True).distinct()


def module_catalog(user, profile: dict) -> list[dict]:
    configured = profile.get("modules") or {}
    businesses = _businesses_for(user)
    property_count = PMProperty.objects.filter(business_id__in=businesses.values_list("id", flat=True)).count()
    rows = [
        ("marketplace", "Local services", True, "/customer/new-request", "Find an optometrist, notary, HVAC company, or submit a repair request."),
        ("calendar", "Calendar", bool(configured.get("calendar")), "/customer/calendar", "Organize the day, conflicts, traffic-aware departure times, and reminders."),
        ("email", "Email", bool(configured.get("email")), "/customer/settings", "Surface important Gmail and Outlook messages as email connections are enabled."),
        ("health", "Health", bool(configured.get("health")), "/customer/health", "Include workouts, nutrition, sleep, and recovery."),
        ("money", "Money", bool(configured.get("money")), "/customer/finance", "Include balances, bills, liabilities, and financial priorities."),
        ("business", "Businesses", businesses.exists(), "/sbo", "Track tickets, team assignments, payments, leads, and operations."),
        ("property", "Rental properties", property_count > 0, "/pm", "Track tenants, rent, maintenance, messages, and projects."),
        ("affiliate", "Affiliate", bool(configured.get("affiliate")), "/customer/affiliate", "Track attributed businesses, commissions, and payouts."),
    ]
    return [{"id": key, "title": title, "connected": connected, "url": url, "benefit": benefit} for key, title, connected, url, benefit in rows]


def setup_score(user, profile: dict) -> int:
    modules = module_catalog(user, profile)
    checks = [
        bool(profile.get("assistant_name")), bool(profile.get("goals")), bool(profile.get("wake_time")),
        bool(profile.get("bedtime")), bool(profile.get("timezone")),
        any(item["connected"] for item in modules if item["id"] != "marketplace"),
        bool(profile.get("permissions")), bool(profile.get("onboarding_complete")),
    ]
    return round(sum(checks) / len(checks) * 100)


def product_payload(user) -> dict:
    settings, profile = load_profile(user)
    billing, _ = UserBillingProfile.objects.get_or_create(user=user)
    live = _deep_merge(DEFAULT_LIVE, profile.get("live") or {})
    access = live_access(user, profile)
    live["access"] = access
    live["included_with_plan"] = access
    if is_test_access(user):
        live.update({"enabled": True, "access": True, "included_with_plan": True})
    home = deepcopy(profile.get("home_location") or {})
    if not home.get("label"):
        home["label"] = settings.default_address or settings.default_zip or ""
    return {
        **profile,
        "product_name": "SYNC Assistant",
        "legacy_product_key": "jarvis",
        "home_location": home,
        "live": live,
        "plan": effective_plan(user, profile),
        "setup_score": setup_score(user, profile),
        "entitlements": entitlements(user, profile),
        "module_catalog": module_catalog(user, profile),
        "plans": PLANS,
        "billing": {
            "subscription_status": billing.subscription_status or "free",
            "stripe_customer_ready": bool(billing.stripe_customer_id),
            "current_period_end": billing.subscription_current_period_end,
            "cancel_at_period_end": billing.subscription_cancel_at_period_end,
            "test_access": is_test_access(user),
        },
        "quick_actions": [
            {"id": "find_service", "label": "Find a local service", "url": "/customer/new-request"},
            {"id": "repair_request", "label": "Request a repair", "url": "/customer/new-request"},
            {"id": "calendar", "label": "Open my calendar", "url": "/customer/calendar"},
            {"id": "health", "label": "Open Health", "url": "/customer/health"},
            {"id": "business", "label": "Review business work", "url": "/sbo"},
            {"id": "property", "label": "Review rental properties", "url": "/pm"},
        ],
        "generated_at": timezone.now(),
    }
