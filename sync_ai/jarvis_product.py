from __future__ import annotations

import os
from copy import deepcopy

from django.utils import timezone

from user_accounts.models import (
    Business,
    CustomerSettings,
    PMProperty,
    UserBillingProfile,
)

TEST_EMAILS = {"jacoblord7@outlook.com"}
DEFAULT_PROFILE = {
    "assistant_name": "SYNC",
    "tone": "CALM",
    "briefing_length": "STANDARD",
    "template": "GENERAL",
    "wake_time": "07:00",
    "bedtime": "22:30",
    "quiet_hours_enabled": False,
    "goals": ["ORGANIZE_DAY", "FIND_LOCAL_SERVICES"],
    "modules": {},
    "permissions": {"view": True, "prepare": True, "confirm": True, "automate": False},
    "onboarding_step": 0,
    "onboarding_complete": False,
    "plan": "BASIC",
}

PLANS = [
    {"id": "BASIC", "name": "Basic", "price": 0, "description": "Marketplace search, service requests, manual schedule and tasks, and a limited briefing."},
    {"id": "PERSONAL", "name": "Personal AI", "price": 12.99, "description": "Voice briefings, overnight preparation, email and calendar intelligence, Health, and Money."},
    {"id": "FAMILY", "name": "Family", "price": 22.99, "description": "Personal AI plus shared schedules, household coordination, and family alerts."},
    {"id": "EXECUTIVE", "name": "Executive", "price": 34.99, "description": "Multiple businesses, rental properties, affiliates, deeper reports, and approved actions."},
]


def is_test_access(user) -> bool:
    configured = {item.strip().lower() for item in (os.getenv("SYNC_JARVIS_TEST_EMAILS") or "").split(",") if item.strip()}
    return (user.email or "").strip().lower() in (TEST_EMAILS | configured)


def settings_for(user):
    return CustomerSettings.objects.get_or_create(user=user)[0]


def load_profile(user) -> tuple[CustomerSettings, dict]:
    settings = settings_for(user)
    root = deepcopy(settings.finance_profile or {})
    profile = deepcopy(DEFAULT_PROFILE)
    profile.update(root.get("jarvis") or {})
    return settings, profile


def save_profile(user, updates: dict) -> dict:
    settings, profile = load_profile(user)
    allowed = set(DEFAULT_PROFILE)
    for key, value in updates.items():
        if key in allowed:
            profile[key] = value
    root = deepcopy(settings.finance_profile or {})
    root["jarvis"] = profile
    settings.finance_profile = root
    settings.save(update_fields=("finance_profile", "updated_at"))
    return profile


def effective_plan(user, profile: dict) -> str:
    return "EXECUTIVE" if is_test_access(user) else str(profile.get("plan") or "BASIC").upper()


def entitlements(user, profile: dict) -> dict:
    plan = effective_plan(user, profile)
    paid = plan != "BASIC"
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
    }


def module_catalog(user, profile: dict) -> list[dict]:
    configured = profile.get("modules") or {}
    business_count = Business.objects.filter(owner=user, is_active=True).count()
    try:
        property_count = PMProperty.objects.filter(manager=user).count()
    except Exception:
        property_count = 0
    rows = [
        ("marketplace", "Local services", True, "/customer/new-request", "Find an optometrist, notary, HVAC company, or submit a repair request."),
        ("calendar", "Calendar", bool(configured.get("calendar")), "/calendar", "Organize the day, conflicts, and future departure reminders."),
        ("email", "Email", bool(configured.get("email")), "/jarvis/setup?step=connections", "Surface important Gmail and Outlook messages."),
        ("health", "Health", bool(configured.get("health")), "/customer/health", "Include workouts, nutrition, sleep, and recovery."),
        ("money", "Money", bool(configured.get("money")), "/customer/finance", "Include bills, plans, and financial priorities."),
        ("business", "Businesses", business_count > 0, "/sbo", "Track tickets, team assignments, payments, leads, and operations."),
        ("property", "Rental properties", property_count > 0, "/pm", "Track tenants, rent, maintenance, messages, and projects."),
        ("affiliate", "Affiliate", bool(configured.get("affiliate")), "/customer/affiliate", "Track attributed businesses, commissions, and payouts."),
    ]
    return [{"id": key, "title": title, "connected": connected, "url": url, "benefit": benefit} for key, title, connected, url, benefit in rows]


def setup_score(user, profile: dict) -> int:
    modules = module_catalog(user, profile)
    checks = [
        bool(profile.get("assistant_name")), bool(profile.get("goals")), bool(profile.get("wake_time")),
        bool(profile.get("bedtime")), bool(profile.get("quiet_hours_enabled")),
        any(item["connected"] for item in modules if item["id"] != "marketplace"),
        bool(profile.get("permissions")), bool(profile.get("onboarding_complete")),
    ]
    return round(sum(checks) / len(checks) * 100)


def product_payload(user) -> dict:
    _, profile = load_profile(user)
    billing, _ = UserBillingProfile.objects.get_or_create(user=user)
    return {
        **profile,
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
            {"id": "calendar", "label": "Open my calendar", "url": "/calendar"},
            {"id": "health", "label": "Open Health", "url": "/customer/health"},
            {"id": "business", "label": "Review business work", "url": "/sbo"},
            {"id": "property", "label": "Review rental properties", "url": "/pm"},
        ],
        "generated_at": timezone.now(),
    }
