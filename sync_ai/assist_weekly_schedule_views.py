"""Founder-only, read-only weekly schedule draft for a saved Victoria assignment.

Never writes calendar, billing, email, or external provider data.
"""
from datetime import datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from user_accounts.models import AuditLog
from personal_calendar.models import PersonalCalendarEvent
from .assist_assignment_views import CREATED
from .assist_pilot_views import _pilot

ACTION = "sync_assist.assignment.schedule_draft"
ZONE = ZoneInfo("America/Chicago")
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

def parse_clock(raw, name):
    try:
        if not isinstance(raw, str) or len(raw) != 5:
            raise ValueError()
        return time.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"{name} must be HH:MM.")

def minutes(clock):
    return clock.hour * 60 + clock.minute

def clock_at(day, clock):
    return datetime.combine(day, clock, tzinfo=ZONE)

def serialize(slot):
    return {"title": slot["title"], "start": slot["start"].isoformat(),
            "end": slot["end"].isoformat(), "category": slot["category"],
            "conflicts": slot.get("conflicts", []), "proposed": True}

class VictoriaWeeklyPlanView(APIView):
    permission_classes = [IsAuthenticated]

    def _assignment(self, request, assignment_id):
        try:
            identifier = str(UUID(str(assignment_id)))
        except (ValueError, TypeError, AttributeError):
            return None
        event = AuditLog.objects.filter(actor=request.user, action=CREATED,
                metadata__assignment_id=identifier).first()
        if event and (event.metadata or {}).get("role") == "CHIEF_OF_STAFF":
            return identifier
        return None

    def get(self, request, assignment_id):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        key = self._assignment(request, assignment_id)
        if not key:
            return Response({"detail": "Victoria assignment not found."}, status=404)
        prior = AuditLog.objects.filter(actor=request.user, action=ACTION,
                                       metadata__assignment_id=key).order_by("-id").first()
        return Response({"draft": (prior.metadata or {}).get("draft") if prior else None,
                         "read_only": True})

    def post(self, request, assignment_id):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        key = self._assignment(request, assignment_id)
        if not key:
            return Response({"detail": "Victoria assignment not found."}, status=404)
        data = request.data
        try:
            start = parse_clock(data.get("work_start"), "Work start")
            end = parse_clock(data.get("work_end"), "Work end")
            gym_at = parse_clock(data.get("gym_time"), "Gym time")
            forge_at = parse_clock(data.get("forge_time"), "Forge time")
            lunch_at = parse_clock(data.get("lunch_time"), "Lunch time")
            email_at = parse_clock(data.get("email_time"), "Email time")
            workdays = data.get("work_days")
            gymdays = data.get("gym_days")
            if not isinstance(workdays, list) or not isinstance(gymdays, list):
                raise ValueError("Select work days and gym days.")
            if any(type(x) is not int or x not in range(7) for x in workdays + gymdays):
                raise ValueError("Days must be numbers from 0 to 6.")
            if minutes(end) <= minutes(start) or minutes(end) - minutes(start) < 60:
                raise ValueError("Working hours must cover at least one hour.")
            if len(set(workdays)) != len(workdays) or len(set(gymdays)) != len(gymdays):
                raise ValueError("Day selections must be unique.")
            if data.get("forge_enabled") not in (True, False) or data.get("lunch_enabled") not in (True, False):
                raise ValueError("Specify morning routine and lunch preferences.")
            if data.get("email_enabled") not in (True, False):
                raise ValueError("Specify email check preference.")
            focus = str(data.get("focus") or "").strip()[:400]
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        # Upcoming Monday (including current Monday) ensures consistent week display.
        today = timezone.localtime(timezone.now(), ZONE).date()
        monday = today - timedelta(days=today.weekday())
        end_date = monday + timedelta(days=7)
        # Only owned active records, including already-synced external calendar events.
        records = list(PersonalCalendarEvent.objects.filter(owner=request.user, status="ACTIVE",
            start_at__lt=datetime.combine(end_date, time.min, tzinfo=ZONE),
            start_at__gte=datetime.combine(monday - timedelta(days=1), time.min, tzinfo=ZONE)
        ).order_by("start_at")[:300])
        existing = []
        for e in records:
            event_end = e.end_at or e.start_at + timedelta(minutes=30)
            existing.append({"id": e.pk, "title": e.title[:160],
                "start": e.start_at.astimezone(ZONE), "end": event_end.astimezone(ZONE),
                "source": e.source})
        # Decision-support only: these instructions are derived from the owner's
        # priorities, not live financial, email, or job-verification data.
        workstreams = [
            ("FINANCE", "Finances and collections", "Check bills, mortgage due dates, rent collection and unanswered Section 8 items against verified records.", "List each confirmed amount, due date, missing record and responsible follow-up."),
            ("PRODUCT", "SyncWorks development", "Choose one product blocker, reproduce it, and run an acceptance test before considering it complete.", "One tested change or an actionable blocker report."),
            ("REVENUE", "Upwork opportunities", "Review suitable projects, validate scope, draft a proposal and request approval before submitting.", "A vetted opportunity and reviewable proposal."),
            ("GROWTH", "Small-business marketing", "Choose a customer segment and prepare one permission-aware marketing or outreach draft.", "One draft and a measurable next step."),
        ]
        focus_lower = focus.lower()
        keys = {
            "FINANCE": ("financ", "rent", "mortgage", "section 8", "payment", "bill"),
            "PRODUCT": ("syncworks", "app", "build", "software", "product"),
            "REVENUE": ("upwork", "freelance", "job"),
            "GROWTH": ("market", "social", "lead", "business", "funnel"),
        }
        selected = [stream for stream in workstreams if any(word in focus_lower for word in keys[stream[0]])]
        if not selected:
            selected = workstreams[:2]
        days = []
        conflict_count = 0
        warnings = []
        if data["lunch_enabled"] and (minutes(lunch_at) < 10 * 60 or minutes(lunch_at) > 15 * 60):
            warnings.append("Lunch is set outside typical midday hours. Confirm AM/PM before adding it to a calendar.")
        if minutes(end) - minutes(start) > 8 * 60:
            warnings.append("Your availability exceeds eight hours; treat this as an available window, not continuous assigned work.")
        def add(slots, date, at, duration, title, category):
            nonlocal conflict_count
            beginning = clock_at(date, at)
            finish = beginning + timedelta(minutes=duration)
            overlapping = [e["title"] for e in existing if e["start"] < finish and e["end"] > beginning]
            if category != "WORK":
                overlapping += [s["title"] for s in slots if s["category"] != "WORK" and s["start"] < finish and s["end"] > beginning]
            if overlapping and category != "WORK":
                conflict_count += 1
            slots.append({"title": title, "start": beginning, "end": finish,
                          "category": category, "conflicts": overlapping[:5]})
        for idx in range(7):
            date = monday + timedelta(days=idx)
            slots = []
            if data["forge_enabled"]:
                add(slots, date, forge_at, 30, "Forge morning routine", "FORGE")
            if idx in gymdays:
                add(slots, date, gym_at, 60, "Gym / workout (plan not generated)", "HEALTH")
            if idx in workdays:
                add(slots, date, start, minutes(end) - minutes(start),
                    "Work availability (not a booked appointment)", "WORK")
                if data["email_enabled"]:
                    add(slots, date, email_at, 30, "Email review and to-do triage", "ADMIN")
            if data["lunch_enabled"]:
                add(slots, date, lunch_at, 45, "Lunch", "PERSONAL")
            management_actions = []
            if idx in workdays:
                for order, (code, title, instruction, result) in enumerate(selected[:3], start=1):
                    management_actions.append({
                        "priority": order, "category": code, "title": title,
                        "instruction": instruction, "done_when": result,
                        "status": "PROPOSED", "requires_review": True,
                        "source": "owner_entered_priorities",
                    })
            committed = [{"title": e["title"], "start": e["start"].isoformat(),
                          "end": e["end"].isoformat(), "source": e["source"],
                          "existing": True} for e in existing if e["start"].date() == date]
            days.append({"date": date.isoformat(), "day": DAY_NAMES[idx],
                         "existing": committed, "management_actions": management_actions, "suggestions": [serialize(s) for s in sorted(slots, key=lambda s: s["start"])]})
        draft = {"week_start": monday.isoformat(), "week_end": (end_date - timedelta(days=1)).isoformat(),
                 "timezone": str(ZONE), "days": days, "calendar_event_count": sum(len(d["existing"]) for d in days),
                 "potential_overlap_count": conflict_count, "focus": focus,
                 "management_mode": "owner_guided_rule_based",
                 "preferences": {key: data.get(key) for key in ("work_start", "work_end", "gym_time", "forge_time", "lunch_time", "email_time", "work_days", "gym_days", "forge_enabled", "lunch_enabled", "email_enabled", "focus")},
                 "warnings": warnings,
                 "connection_note": "Only appointments currently in SyncWorks Calendar were read; external calendars not yet synced may be missing.",
                 "finance_note": "Payment amounts, due dates, mortgage balances, and rent collections were not retrieved. Connect verified financial and property sources before adding these to the schedule.",
                 "health_note": "Gym sessions are proposed time blocks, not generated workout prescriptions.",
                 "approval_required": True, "calendar_writes": 0, "external_actions": 0,
                 "created_at": timezone.now().isoformat()}
        AuditLog.objects.create(actor=request.user, action=ACTION,
                                metadata={"assignment_id": key, "draft": draft})
        return Response({"draft": draft, "read_only": True, "notice": "Draft saved for review. No calendar events were created or changed."}, status=201)
