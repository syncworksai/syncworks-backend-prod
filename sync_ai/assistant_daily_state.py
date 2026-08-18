from __future__ import annotations

from datetime import datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Q
from django.utils import timezone

from customer_health.models import CustomerHealthProfile
from personal_calendar.models import PersonalCalendarEvent
from user_accounts.models import (
    Business,
    BusinessMember,
    FinanceAccount,
    FinanceLiability,
    FinanceObligation,
    PMProperty,
    PMWorkOrder,
    Ticket,
)

from .health_context import build_sync_health_context
from .jarvis_product import entitlements, live_access, load_profile
from .live_travel import leave_plan, route_minutes
from .live_weather import weather_for_location


CLOSED_TICKET_STATUSES = {
    Ticket.Status.COMPLETED,
    Ticket.Status.PAID,
    Ticket.Status.CANCELLED,
    Ticket.Status.CLOSED,
}


def _tz(profile: dict):
    value = str(profile.get("timezone") or "").strip()
    if value:
        try:
            return ZoneInfo(value)
        except ZoneInfoNotFoundError:
            pass
    return timezone.get_current_timezone()


def _businesses_for(user):
    member_ids = BusinessMember.objects.filter(user=user, is_active=True).values_list("business_id", flat=True)
    return Business.objects.filter(Q(owner=user) | Q(id__in=member_ids), is_active=True).distinct()


def _decimal(value):
    if value is None:
        return None
    try:
        return float(Decimal(value))
    except Exception:
        return None


def _calendar_state(user, profile: dict, now_local, live_enabled: bool):
    tz = now_local.tzinfo
    start_local = datetime.combine(now_local.date(), time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    events = list(
        PersonalCalendarEvent.objects.filter(
            owner=user,
            status="ACTIVE",
            start_at__gte=start_local.astimezone(dt_timezone.utc),
            start_at__lt=end_local.astimezone(dt_timezone.utc),
        ).order_by("start_at")[:20]
    )
    live = profile.get("live") or {}
    home = profile.get("home_location") or {}
    default_arrival = int(live.get("arrival_buffer_minutes") or 15)
    reminder_minutes = int(live.get("departure_reminder_minutes") or 10)
    rows = []
    for event in events:
        event_start = timezone.localtime(event.start_at, tz)
        destination = {
            "latitude": event.latitude,
            "longitude": event.longitude,
            "label": event.location_name or event.address_line1 or "",
        }
        metadata = event.metadata if isinstance(event.metadata, dict) else {}
        travel = {"available": False, "reason": "LIVE_REQUIRED"}
        if live_enabled:
            if metadata.get("travel_minutes") not in (None, ""):
                try:
                    travel = {
                        "available": True,
                        "minutes": max(1, int(metadata.get("travel_minutes"))),
                        "traffic_aware": False,
                        "provider": "EVENT_METADATA",
                    }
                except (TypeError, ValueError):
                    travel = {"available": False, "reason": "TRAVEL_TIME_REQUIRED"}
            else:
                travel = route_minutes(home, destination)
        arrival_buffer = int(event.arrival_buffer_minutes if event.arrival_buffer_minutes is not None else default_arrival)
        departure = leave_plan(
            event_start=event_start,
            arrival_buffer_minutes=arrival_buffer,
            reminder_minutes=reminder_minutes,
            travel=travel,
        )
        rows.append({
            "id": event.id,
            "title": event.title,
            "start_at": event_start.isoformat(),
            "end_at": timezone.localtime(event.end_at, tz).isoformat() if event.end_at else None,
            "location": event.location_name or event.address_line1 or "",
            "address": ", ".join(part for part in [event.address_line1, event.city, event.state, event.postal_code] if part),
            "source": event.source,
            "arrival_buffer_minutes": arrival_buffer,
            "departure": departure,
            "url": "/customer/calendar",
        })
    next_event = next((row for row in rows if datetime.fromisoformat(row["start_at"]) >= now_local), None)
    return {
        "available": True,
        "count_today": len(rows),
        "events": rows,
        "next_event": next_event,
    }


def _health_state(user):
    compact = build_sync_health_context(user)
    if not compact.get("available"):
        return compact
    health = CustomerHealthProfile.objects.filter(user=user).first()
    profile = health.profile_json if health and isinstance(health.profile_json, dict) else {}
    snapshot = health.snapshot_json if health and isinstance(health.snapshot_json, dict) else {}
    nutrition_plan = profile.get("nutrition_plan") or profile.get("meal_plan") or {}
    breakfast = None
    if isinstance(nutrition_plan, dict):
        breakfast = nutrition_plan.get("breakfast") or nutrition_plan.get("morning")
    if breakfast in (None, ""):
        breakfast = profile.get("breakfast") or snapshot.get("planned_breakfast")
    meals_logged = ((compact.get("today") or {}).get("meals_logged"))
    return {
        **compact,
        "nutrition": {
            "planned_breakfast": breakfast,
            "breakfast_logged": bool(snapshot.get("breakfast_logged")) or bool(meals_logged and meals_logged > 0),
            "meals_logged": meals_logged,
            "protein_grams": (compact.get("today") or {}).get("protein_grams"),
            "protein_goal_grams": (compact.get("today") or {}).get("protein_goal_grams"),
        },
    }


def _finance_state(user, today):
    accounts = FinanceAccount.objects.filter(user=user, is_hidden=False)
    obligations = FinanceObligation.objects.filter(user=user, active=True, next_due_date__isnull=False, next_due_date__lte=today + timedelta(days=7)).order_by("next_due_date")[:10]
    liabilities = FinanceLiability.objects.filter(user=user, next_payment_date__isnull=False, next_payment_date__lte=today + timedelta(days=7)).order_by("next_payment_date")[:10]
    checking = [
        {"name": row.name, "balance": _decimal(row.current_balance), "available": _decimal(row.available_balance), "mask": row.mask}
        for row in accounts.filter(kind=FinanceAccount.Kind.CHECKING)[:5]
    ]
    credit_cards = [
        {"name": row.name, "balance": _decimal(row.current_balance), "limit": _decimal(row.credit_limit), "mask": row.mask}
        for row in accounts.filter(kind=FinanceAccount.Kind.CREDIT_CARD)[:10]
    ]
    due = [
        {
            "type": "obligation",
            "name": row.name,
            "due_date": row.next_due_date.isoformat(),
            "amount": _decimal(row.expected_amount or row.minimum_amount),
            "autopay": row.autopay,
        }
        for row in obligations
    ]
    due.extend({
        "type": "liability",
        "name": row.name,
        "due_date": row.next_payment_date.isoformat(),
        "amount": _decimal(row.next_payment_amount or row.minimum_payment),
        "autopay": False,
    } for row in liabilities)
    due.sort(key=lambda item: item.get("due_date") or "9999-12-31")
    due_total = sum(Decimal(str(item["amount"])) for item in due if item.get("amount") is not None)
    return {
        "available": accounts.exists() or bool(due),
        "checking": checking,
        "credit_cards": credit_cards,
        "due_next_7_days": due[:12],
        "known_due_total_next_7_days": float(due_total),
    }


def _business_state(user):
    businesses = _businesses_for(user)
    rows = []
    for business in businesses[:10]:
        tickets = Ticket.objects.filter(Q(assigned_business=business) | Q(payer_business=business), archived_at__isnull=True).distinct().exclude(status__in=CLOSED_TICKET_STATUSES)
        attention = tickets.filter(status__in=[Ticket.Status.NEW, Ticket.Status.NEEDS_QUOTE, Ticket.Status.AWAITING_APPROVAL, Ticket.Status.QUOTE_REJECTED])
        rows.append({
            "id": business.id,
            "name": business.name,
            "active_tickets": tickets.count(),
            "needs_attention": attention.count(),
            "unassigned": tickets.filter(assigned_member__isnull=True).count(),
            "url": "/sbo",
        })
    return {"available": bool(rows), "businesses": rows, "needs_attention": sum(row["needs_attention"] for row in rows)}


def _property_state(user):
    businesses = _businesses_for(user)
    business_ids = businesses.values_list("id", flat=True)
    properties = PMProperty.objects.filter(business_id__in=business_ids)
    workorders = PMWorkOrder.objects.filter(business_id__in=business_ids).exclude(status__in=[PMWorkOrder.Status.COMPLETED, PMWorkOrder.Status.CANCELED])
    urgent = workorders.filter(priority=PMWorkOrder.Priority.URGENT)
    return {
        "available": properties.exists(),
        "property_count": properties.count(),
        "open_workorders": workorders.count(),
        "urgent_workorders": urgent.count(),
        "unassigned_workorders": workorders.filter(assigned_member__isnull=True, marketplace_ticket__isnull=True).count(),
        "items": [
            {
                "id": row.id,
                "title": row.title,
                "priority": row.priority,
                "status": row.status,
                "property": row.property.name if row.property else "",
                "url": "/pm",
            }
            for row in workorders.select_related("property")[:5]
        ],
    }


def _todo_state(profile: dict):
    todos = profile.get("todos") if isinstance(profile.get("todos"), list) else []
    open_rows = []
    for index, item in enumerate(todos[:100]):
        if not isinstance(item, dict) or item.get("completed"):
            continue
        open_rows.append({
            "id": item.get("id") or str(index),
            "title": str(item.get("title") or item.get("text") or "Task")[:180],
            "due_at": item.get("due_at"),
            "priority": item.get("priority") or "normal",
        })
    return {"available": True, "open_count": len(open_rows), "items": open_rows[:10]}


def _priority_items(state: dict):
    items = []
    weather = state.get("weather") or {}
    if weather.get("available") and weather.get("alerts"):
        for alert in weather["alerts"][:2]:
            items.append({"category": "weather", "priority": "urgent", "title": alert.get("event") or "Weather alert", "detail": alert.get("headline") or "Active weather alert"})
    calendar = state.get("calendar") or {}
    next_event = calendar.get("next_event") or {}
    departure = next_event.get("departure") or {}
    if departure.get("available"):
        items.append({"category": "calendar", "priority": "high", "title": f"Leave for {next_event.get('title')}", "detail": f"Recommended leave time: {departure.get('leave_by')}", "action": {"label": "Open calendar", "url": "/customer/calendar"}})
    health = state.get("health") or {}
    today = health.get("today") or {}
    if health.get("available") and not today.get("workout_completed") and not today.get("planned_workout"):
        items.append({"category": "health", "priority": "normal", "title": "No workout planned today", "detail": "Your Health plan has no workout scheduled for today.", "action": {"label": "Open Health", "url": "/customer/health"}})
    nutrition = health.get("nutrition") or {}
    if nutrition.get("planned_breakfast") and not nutrition.get("breakfast_logged"):
        items.append({"category": "health", "priority": "normal", "title": "Breakfast is not logged", "detail": f"Planned breakfast: {nutrition.get('planned_breakfast')}"})
    finance = state.get("money") or {}
    if finance.get("due_next_7_days"):
        nearest = finance["due_next_7_days"][0]
        items.append({"category": "money", "priority": "high" if nearest.get("due_date") == state.get("local_date") else "normal", "title": f"Payment due: {nearest.get('name')}", "detail": f"Due {nearest.get('due_date')}"})
    prop = state.get("properties") or {}
    if prop.get("urgent_workorders"):
        items.append({"category": "property", "priority": "urgent", "title": f"{prop.get('urgent_workorders')} urgent property work order(s)", "detail": "Property maintenance needs attention.", "action": {"label": "Open properties", "url": "/pm"}})
    business = state.get("business") or {}
    if business.get("needs_attention"):
        items.append({"category": "business", "priority": "high", "title": f"{business.get('needs_attention')} business item(s) need attention", "detail": "Tickets are waiting for action.", "action": {"label": "Open Business", "url": "/sbo"}})
    order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    return sorted(items, key=lambda item: order.get(item.get("priority"), 9))[:8]


def build_daily_state(user):
    _, profile = load_profile(user)
    tz = _tz(profile)
    now_local = timezone.now().astimezone(tz)
    ent = entitlements(user, profile)
    is_live = live_access(user, profile) and bool((profile.get("live") or {}).get("enabled", True))
    weather = {"available": False, "reason": "LIVE_REQUIRED"}
    if is_live and (profile.get("live") or {}).get("weather_enabled", True):
        weather = weather_for_location(profile.get("home_location") or {})
    state = {
        "product_name": "SYNC Assistant",
        "generated_at": timezone.now().isoformat(),
        "local_time": now_local.isoformat(),
        "local_date": now_local.date().isoformat(),
        "timezone": str(tz),
        "greeting": "Good morning" if now_local.hour < 12 else "Good afternoon" if now_local.hour < 18 else "Good evening",
        "user_name": getattr(user, "first_name", "") or (str(getattr(user, "email", "")).split("@", 1)[0] if getattr(user, "email", "") else "there"),
        "entitlements": ent,
        "live": {"enabled": is_live, "access": ent.get("sync_assistant_live", False), "preferences": profile.get("live") or {}},
        "weather": weather,
        "calendar": _calendar_state(user, profile, now_local, is_live),
        "health": _health_state(user),
        "tasks": _todo_state(profile),
        "money": _finance_state(user, now_local.date()),
        "business": _business_state(user),
        "properties": _property_state(user),
        "email": {"available": False, "reason": "NEXT_CONNECTION_BUILD"},
        "news": {
            "available": False,
            "reason": "NEWS_PROVIDER_NEXT_PHASE" if is_live else "LIVE_REQUIRED",
            "mode": (profile.get("live") or {}).get("news_mode", "MAJOR_ONLY"),
            "topics": (profile.get("live") or {}).get("news_topics", []),
            "sports": (profile.get("live") or {}).get("sports", []),
        },
    }
    state["needs_attention"] = _priority_items(state)
    state["recommended_next"] = state["needs_attention"][0] if state["needs_attention"] else {
        "category": "day",
        "priority": "normal",
        "title": "Your day is clear",
        "detail": "No connected area currently needs immediate attention.",
    }
    return state
