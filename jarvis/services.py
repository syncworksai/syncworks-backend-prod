from __future__ import annotations

import os

from django.utils import timezone

from user_accounts.models import Business, PMProperty, UserBillingProfile

from .models import JarvisProfile

TEST_EMAILS = {"jacoblord7@outlook.com"}


def is_test_access(user) -> bool:
    configured = {value.strip().lower() for value in (os.getenv("SYNC_JARVIS_TEST_EMAILS") or "").split(",") if value.strip()}
    return (user.email or "").strip().lower() in (TEST_EMAILS | configured)


def effective_plan(user, profile: JarvisProfile) -> str:
    return JarvisProfile.Plan.EXECUTIVE if is_test_access(user) else profile.plan


def entitlements(user, profile: JarvisProfile) -> dict:
    plan = effective_plan(user, profile)
    paid = plan != JarvisProfile.Plan.BASIC or is_test_access(user)
    return {
        "plan": plan,
        "test_access": is_test_access(user),
        "voice": paid,
        "overnight_briefing": paid,
        "email_intelligence": paid,
        "calendar_intelligence": paid,
        "health": paid,
        "money": paid,
        "business": plan in {JarvisProfile.Plan.PERSONAL, JarvisProfile.Plan.FAMILY, JarvisProfile.Plan.EXECUTIVE},
        "property_management": plan == JarvisProfile.Plan.EXECUTIVE,
        "family": plan in {JarvisProfile.Plan.FAMILY, JarvisProfile.Plan.EXECUTIVE},
        "approved_actions": paid,
    }


def module_catalog(user, profile: JarvisProfile) -> list[dict]:
    owned_businesses = Business.objects.filter(owner=user, is_active=True).count()
    properties = PMProperty.objects.filter(owner=user).count() if hasattr(PMProperty, "owner") else 0
    configured = profile.modules or {}
    items = [
        ("marketplace", "Find local services", True, "/customer/new-request", "Find an optometrist, notary, HVAC company, or submit a service request."),
        ("calendar", "Calendar", bool(configured.get("calendar")), "/calendar", "Organize the day and prepare departure reminders."),
        ("email", "Email", bool(configured.get("email")), "/jarvis/setup?step=connections", "Surface important Gmail or Outlook messages."),
        ("health", "Health", bool(configured.get("health")), "/customer/health", "Include workouts, nutrition, sleep, and recovery."),
        ("money", "Money", bool(configured.get("money")), "/customer/finance", "Include bills, plans, and financial priorities."),
        ("business", "Businesses", owned_businesses > 0, "/sbo", "Track tickets, teams, payments, leads, and operations."),
        ("property", "Rental properties", properties > 0, "/pm", "Track tenants, maintenance, rent, messages, and projects."),
        ("affiliate", "Affiliate", bool(configured.get("affiliate")), "/customer/affiliate", "Track attributed businesses, commissions, and payouts."),
    ]
    return [{"id": key, "title": title, "connected": connected, "url": url, "benefit": benefit} for key, title, connected, url, benefit in items]


def setup_score(user, profile: JarvisProfile) -> int:
    checkpoints = [
        bool(profile.assistant_name),
        bool(profile.goals),
        bool(profile.wake_time),
        bool(profile.bedtime),
        profile.quiet_hours_enabled,
        any(item["connected"] for item in module_catalog(user, profile) if item["id"] != "marketplace"),
        bool(profile.permissions),
        profile.onboarding_complete,
    ]
    return round(sum(checkpoints) / len(checkpoints) * 100)


def billing_snapshot(user, profile: JarvisProfile) -> dict:
    billing, _ = UserBillingProfile.objects.get_or_create(user=user)
    return {
        "plan": effective_plan(user, profile),
        "subscription_status": profile.subscription_status,
        "test_access": is_test_access(user),
        "stripe_customer_ready": bool(billing.stripe_customer_id),
        "subscription_current_period_end": billing.subscription_current_period_end,
        "cancel_at_period_end": billing.subscription_cancel_at_period_end,
    }
