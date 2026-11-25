"""Chief of Staff issue register and deterministic on-demand briefing for private pilot.

Cases are owner-entered and append-only. No claim of independent reconciliation or
mailbox access. Resolution requires an explicit owner action with a resolution note.
"""
from collections import Counter
from uuid import uuid4
from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from user_accounts.models import AuditLog
from .assist_pilot_views import _pilot
from .assist_daily_views import _build
from .assist_outlook_views import _settings, _latest
from .assist_assignment_views import _snapshot as assignment_snapshot
from .assist_property_portfolio import PropertyPortfolioBriefView

CREATED="sync_assist.chief.case_created"
CHANGED="sync_assist.chief.case_changed"
SEVERITIES={"HIGH","MEDIUM","LOW"}
AREAS={"PROPERTY","BUSINESS","GROWTH","FINANCE","PERSONAL"}
STATES={"OPEN","WAITING","RESOLVED"}
MAX_CASES=100

def _cases(user):
    records={}
    for event in AuditLog.objects.filter(actor=user,action__in=[CREATED,CHANGED]).order_by("id"):
        m=event.metadata or {}
        key=str(m.get("case_id") or "")
        if event.action==CREATED:
            if not key or key in records:continue
            records[key]={
                "id":key,"title":m.get("title",""),"details":m.get("details",""),
                "next_step":m.get("next_step",""),"category":m.get("category","BUSINESS"),
                "priority":m.get("priority","MEDIUM"),"status":"OPEN",
                "resolution_note":"","created_at":event.created_at.isoformat(),
                "updated_at":event.created_at.isoformat(),"source":"owner_entered",
            }
        elif key in records:
            state=str(m.get("status") or "")
            if state in STATES:
                records[key]["status"]=state
                records[key]["resolution_note"]=str(m.get("resolution_note") or "")
                records[key]["updated_at"]=event.created_at.isoformat()
    return sorted(records.values(),key=lambda x:(
        x["status"]=="RESOLVED",x["status"]=="WAITING",
        {"HIGH":0,"MEDIUM":1,"LOW":2}.get(x["priority"],2),x["created_at"]
    ))

class JarvisCasesView(APIView):
    permission_classes=[IsAuthenticated]
    def get(self,request):
        if not _pilot(request.user):return Response({"detail":"Private pilot only."},status=403)
        cases=_cases(request.user)
        return Response({"cases":cases,"counts":dict(Counter(x["status"] for x in cases)),
            "notice":"Owner-entered case files. Jarvis has not independently verified amounts or read associated email threads."})

    def post(self,request):
        if not _pilot(request.user):return Response({"detail":"Private pilot only."},status=403)
        title=str(request.data.get("title") or "").strip()
        details=str(request.data.get("details") or "").strip()
        next_step=str(request.data.get("next_step") or "").strip()
        category=str(request.data.get("category") or "").upper().strip()
        priority=str(request.data.get("priority") or "").upper().strip()
        if not title or len(title)>140 or len(details)>2000 or len(next_step)>500 or category not in AREAS or priority not in SEVERITIES:
            return Response({"detail":"Enter a valid title, details, next step, category and priority."},status=400)
        with transaction.atomic():
            from django.contrib.auth import get_user_model
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if AuditLog.objects.filter(actor=request.user,action=CREATED).count()>=MAX_CASES:
                return Response({"detail":"Private pilot case limit reached."},status=429)
            case_id=str(uuid4())
            AuditLog.objects.create(actor=request.user,action=CREATED,metadata={
                "case_id":case_id,"title":title,"details":details,
                "next_step":next_step,"category":category,"priority":priority,
                "origin":"manual","verified":False,"external_actions":False,
            })
        return Response({"case_id":case_id,"cases":_cases(request.user)},status=201)

class JarvisCaseDecisionView(APIView):
    permission_classes=[IsAuthenticated]
    def post(self,request,case_id):
        if not _pilot(request.user):return Response({"detail":"Private pilot only."},status=403)
        state=str(request.data.get("status") or "").strip().upper()
        note=str(request.data.get("resolution_note") or "").strip()
        if state not in STATES or len(note)>1000 or (state=="RESOLVED" and len(note)<8):
            return Response({"detail":"Valid status required. Resolution needs a note describing evidence or owner confirmation."},status=400)
        with transaction.atomic():
            from django.contrib.auth import get_user_model
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            current=next((x for x in _cases(request.user) if x["id"]==str(case_id)),None)
            if not current:return Response({"detail":"Case not found."},status=404)
            AuditLog.objects.create(actor=request.user,action=CHANGED,metadata={
                "case_id":case_id,"status":state,"resolution_note":note,
                "external_actions":False,"owner_confirmed":True,
            })
        return Response({"cases":_cases(request.user)})

class JarvisChiefBriefingView(APIView):
    permission_classes=[IsAuthenticated]
    def get(self,request):
        if not _pilot(request.user):return Response({"detail":"Private pilot only."},status=403)
        daily=_build(request.user)
        cases=_cases(request.user)
        open_cases=[x for x in cases if x["status"]!="RESOLVED"]
        tasks=[x for x in daily["items"] if x["status"]=="OPEN"]
        high=[x for x in tasks if x["priority"]=="HIGH"]
        priority_cases=[x for x in open_cases if x["priority"]=="HIGH"]
        pending_assignments=[x for x in assignment_snapshot(request.user)["assignments"] if x["state"]=="AWAITING_REVIEW"]
        cfg=_settings()
        outlook_connected=bool(cfg and _latest(request.user))
        portfolio = PropertyPortfolioBriefView().get(request).data
        pm_totals = portfolio.get("operations_totals") or {}
        pm_properties = portfolio.get("properties") or []
        pm_actions = sorted(
            [p for p in pm_properties if
             p.get("operations", {}).get("overdue_projects", 0)
             or p.get("operations", {}).get("recorded_leases_ending_within_60_days", 0)
             or p.get("correspondence_count", 0)],
            key=lambda p: (
                -(p.get("operations", {}).get("overdue_projects", 0)),
                -(p.get("operations", {}).get("recorded_leases_ending_within_60_days", 0)),
                -(p.get("correspondence_count", 0)),
            ),
        )
        sections=[
            {"key":"today","title":"Today","headline":f"{len(tasks)} open tasks, {len(high)} high priority","items":[
                {"title":x["title"],"source":x["source"],"category":x["category"],"next_action":x["action"]}
                for x in tasks[:3]],"scope":"Owner tasks and selected SyncWorks records"},
            {"key":"cases","title":"Unresolved issues","headline":f"{len(open_cases)} unresolved case files ({len(priority_cases)} high priority)","items":[
                {"title":x["title"],"source":"owner_entered","category":x["category"],"next_action":x["next_step"] or "Review case"}
                for x in open_cases[:3]],"scope":"Cases manually entered or updated by account owner"},
            {"key":"delegation","title":"AI assignments awaiting review","headline":f"{len(pending_assignments)} tasks or tickets need owner review","items":[{"title":str(x.get("description") or x["role"].replace("_"," ").title())[:180]+(f" #{x['ticket_id']}" if x.get("ticket_id") else ""),"source":"owner_assigned","category":"BUSINESS","next_action":x["suggested_next_action"]} for x in pending_assignments[:3]],"scope":"Review-only owner assignments; no external actions"},
            {"key":"portfolio","title":"Sarah · Property Management","headline":f"{len(pm_actions)} properties with recorded follow-up evidence","items":[
                {"title":p["name"],"source":"property_management_and_reviewed_correspondence","category":"PROPERTY",
                 "next_action":f"Review {p['operations']['overdue_projects']} overdue projects, {p['operations']['recorded_leases_ending_within_60_days']} upcoming lease end dates, {p['correspondence_count']} reviewed email references"}
                for p in pm_actions[:5]],"scope":"Owner-scoped PM project status, recorded lease dates and reviewed email references; no payment or inspection verification"},
            {"key":"sarah_correspondence","title":"Sarah · Correspondence follow-ups",
             "headline":f"{sum(len(p.get('correspondence_issues', [])) for p in pm_properties)} issue categories to verify",
             "items":[{"title":f"{p['name']} · {issue['category'].title()}",
                       "source":"sarah_reviewed_correspondence","category":"PROPERTY",
                       "next_action":issue["next_action"],"priority":issue["priority"],
                       "detail_url":p["detail_url"],"latest_subject":issue.get("latest_subject"),
                       "email_count":issue["email_count"]}
                      for p, issue in sorted(
                          [(p, i) for p in pm_properties for i in p.get("correspondence_issues", [])],
                          key=lambda pair: (pair[1]["priority"] != "HIGH", pair[0]["id"], pair[1]["category"])
                      )[:15]],
             "scope":"Suggested verification actions from owner-reviewed emails; no payment, inspection or resolution confirmed."},
            {"key":"email","title":"Email","headline":"Outlook connected; open Mail Desk for an on-demand inbox brief" if outlook_connected else "Outlook is not connected inside SyncWorks","items":[],"scope":"Reviewed property email reference counts only; no direct mailbox scan"},
        ]
        # Reuse the existing owner-scoped daily context instead of inventing
        # weather, calendar or finance data. Failure must not hide other work.
        from .assistant_daily_state import build_daily_state
        from .assist_growth_prospects import _snapshot as prospect_snapshot
        from .assist_workday_views import _snapshot as workday_snapshot
        from zoneinfo import ZoneInfo
        local = timezone.now().astimezone(ZoneInfo("America/Chicago"))
        context = {"local_time": local.isoformat(), "local_date": local.date().isoformat(),
                   "timezone": "America/Chicago", "weather": {"available": False},
                   "calendar": {"available": False}, "money": {"available": False},
                   "status": "UNAVAILABLE"}
        try:
            state = build_daily_state(request.user)
            context.update({k: state.get(k) for k in ("local_time", "local_date", "timezone", "weather", "calendar", "money", "business", "personal_requests", "needs_attention", "health")})
            context["status"] = "CONNECTED_RECORDS"
        except Exception:
            import logging
            logging.getLogger(__name__).warning("Executive daily context unavailable", exc_info=False)
        for key, title, summary, link in [
            ("weather", "Local weather", "Weather forecast", "/customer/weather"),
            ("calendar", "Today's schedule", "Calendar appointments", "/calendar"),
            ("money", "Personal finances", "Recorded accounts and upcoming obligations", "/customer/finance"),
            ("business", "Business operations", "Recorded business tickets needing attention", "/sbo"),
            ("personal_requests", "Personal requests", "Open personal service requests", "/customer/tickets"),
        ]:
            data = context.get(key) or {}
            available = bool(data.get("available"))
            items = []
            if available and key == "weather":
                period = data.get("current_period") or {}
                items = [{"title": str(period.get("short_forecast") or "Forecast available"),
                          "next_action": "Review forecast and alerts", "source": "weather", "category": "PERSONAL"}]
            elif available and key == "calendar":
                items = [{"title": row.get("title"), "next_action": row.get("start_at"), "source": "calendar", "category": "PERSONAL"} for row in data.get("events", [])[:5]]
            elif available and key == "money":
                items = [{"title": row.get("name"), "next_action": "Review payment due " + str(row.get("due_date")), "source": "finance_records", "category": "FINANCE"} for row in data.get("due_next_7_days", [])[:5]]
            elif available and key == "business":
                items = [{"title": row.get("name"), "next_action": f"Review {row.get('needs_attention', 0)} tickets needing attention", "source": "business_records", "category": "BUSINESS"} for row in data.get("businesses", [])[:5]]
            elif available and key == "personal_requests":
                items = [{"title": row.get("title"), "next_action": row.get("status_label"), "source": "personal_requests", "category": "PERSONAL"} for row in data.get("items", [])[:5]]
            sections.append({"key": key, "title": title, "headline": summary if available else "Source unavailable or not configured", "items": items, "scope": "Existing account records; no external actions", "detail_url": link})
        health = context.get("health") or {}
        today_health = health.get("today") or {}
        nutrition = health.get("nutrition") or {}
        health_items = []
        if health.get("available"):
            workout = today_health.get("planned_workout")
            if workout:
                health_items.append({"title": "Planned workout", "next_action": str(workout)[:300], "source": "health_records"})
            breakfast = nutrition.get("planned_breakfast")
            if breakfast:
                health_items.append({"title": "Nutrition plan", "next_action": str(breakfast)[:300], "source": "health_records"})
        sections.append({"key": "health", "title": "Health and fitness",
            "headline": "Review your recorded wellness plan" if health.get("available") else "Health information unavailable",
            "items": health_items, "detail_url": "/customer/health",
            "scope": "Recorded wellness plans only; no inferred readiness or medical advice."})
        prospects = prospect_snapshot(request.user)
        counts = prospects["counts"]
        actionable = {"RESEARCH", "READY_FOR_REVIEW", "CONTACTED_MANUALLY", "RESPONDED", "DEMO_BOOKED", "TRIAL"}
        sections.append({"key": "scarlett_sales", "title": "Olivia · Sales and lead generation",
            "headline": f"{sum(counts.get(k, 0) for k in actionable)} active prospects in saved pipeline",
            "items": [{"title": row["company"], "source": "saved_prospect", "category": "GROWTH",
                       "next_action": "Review pipeline stage: " + row["stage"]} for row in prospects["prospects"] if row.get("stage") in actionable][:8],
            "scope": "Saved prospects only; no new leads discovered or contacted by this briefing."})
        goals = workday_snapshot(request.user)["goals"]
        for role, name, key in [("MARKETING_MANAGER", "Naomi · Marketing", "elizabeth_marketing"),
                                ("RESEARCH_ANALYST", "Sophia · Research", "sophia_research"),
                                ("CHIEF_OF_STAFF", "Sydney · Product and executive work", "victoria_work"),
                                ("EXECUTIVE_ASSISTANT", "Christy · Executive assistance", "christy_work"),
                                ("BUSINESS_MANAGER", "Whitney · Operations", "whitney_work"),
                                ("TECHNOLOGY_RESEARCH", "Yasmine · Technology research", "yasmine_work"),
                                ("QUALITY_ASSURANCE", "Kylee · Quality assurance", "kylee_work")]:
            work = [(g, s) for g in goals for s in g.get("steps", []) if s.get("role") == role and s.get("status") != "COMPLETED"]
            sections.append({"key": key, "title": name, "headline": f"{len(work)} recorded assignments needing attention",
                "items": [{"title": s["task"], "source": "workday_assignment", "category": "BUSINESS",
                           "next_action": s.get("status"), "goal_id": g["id"], "step_id": s["id"]} for g, s in work[:8]],
                "scope": "Recorded assignments only; no claim of autonomous execution or completed audits."})
        from user_accounts.models.support_requests import SupportRequest
        from user_accounts.viewsets.support_requests import _is_platform_admin
        support = {"available": False, "open": None, "in_progress": None}
        if _is_platform_admin(request.user):
            queue = SupportRequest.objects.filter(status__in=["OPEN", "IN_PROGRESS"])
            support = {"available": True, "open": queue.filter(status="OPEN").count(),
                       "in_progress": queue.filter(status="IN_PROGRESS").count()}
            actions = {"BUG": "Reproduce the reported issue and register verified defects for product review.",
                       "BILLING": "Review the billing record before proposing a response.",
                       "UNLOCK": "Verify account eligibility and escalate access issues.",
                       "FEATURE": "Assess the request for the product backlog."}
            sections.append({"key": "customer_support", "title": "Rebecca · Customer Support",
                "headline": f"{support['open']} open · {support['in_progress']} in progress",
                "items": [{"title": f"Support #{row.id} · {row.title or row.kind}",
                           "source": "platform_support", "category": "BUSINESS",
                           "next_action": actions.get(row.kind, "Review the request and prepare an appropriate response."),
                           "detail_url": "/platform/support", "support_id": row.id,
                           "status": row.status}
                          for row in queue.order_by("created_at", "id")[:10]],
                "scope": "Platform-admin-only active support queue; no responses sent or ticket status changes.",
                "detail_url": "/platform/support"})
        else:
            sections.append({"key": "customer_support", "title": "Customer Support",
                "headline": "Platform administrator access required", "items": [],
                "scope": "No platform support records accessed."})
        from personal_calendar.models import PersonalCalendarEvent
        from datetime import timedelta
        rows = PersonalCalendarEvent.objects.filter(owner=request.user, status="ACTIVE")
        workspace = list(rows.filter(metadata__entity_type__in=["PROJECT", "TASK"]).order_by("id")[:1000])
        projects = []
        for row in workspace:
            meta = row.metadata or {}
            if meta.get("entity_type") != "PROJECT":
                continue
            linked = [t for t in workspace if (t.metadata or {}).get("entity_type") == "TASK" and str((t.metadata or {}).get("project_id")) == str(row.pk)]
            done = sum((t.metadata or {}).get("task_status") == "DONE" for t in linked)
            projects.append({"id": row.pk, "title": row.title, "status": meta.get("project_status", "ACTIVE"),
                             "total": len(linked), "done": done, "next_tasks": [{"id": t.pk, "title": t.title} for t in linked if (t.metadata or {}).get("task_status", "OPEN") == "OPEN"][:5]})
        active_projects = [p for p in projects if p["status"] == "ACTIVE"]
        sections.append({"key":"production_project","title":"Active projects",
                         "headline":f"{len(active_projects)} active projects in the workspace",
                         "items":[{"title": t["title"], "next_action": "Review project: " + p["title"], "detail_url":"/customer/projects"} for p in active_projects for t in p["next_tasks"]][:10],
                         "scope":"Recorded task completion only; not a software readiness audit."})
        schedule = []
        for event in rows.filter(start_at__lt=local + timedelta(days=31), end_at__gt=local-timedelta(days=1)).order_by("start_at")[:300]:
            meta = event.metadata or {}
            if meta.get("entity_type") in {"PROJECT","TASK"} or meta.get("task_unscheduled"):
                continue
            start, end = event.start_at, event.end_at
            status = "ENDED" if end and end <= local else "IN_PROGRESS" if start <= local else "UPCOMING"
            schedule.append({"id":event.pk,"title":event.title,"start_at":start.isoformat(),"end_at":end.isoformat() if end else None,
                             "status":status,"minutes_until":int((start-local).total_seconds()/60)})
        return Response({
            "project_progress": projects,
            "schedule_outlook": schedule,
            "support": support,
            "executive_context": context,
            "date":context["local_date"],"generated_at":timezone.now().isoformat(),"mode":"on_demand",
            "sections":sections,"counts":{
                "tasks_open":len(tasks),"tasks_high":len(high),
                "cases_open":len(open_cases),"cases_high":len(priority_cases),
                "ai_assignments_pending":len(pending_assignments),
            },"outlook_connected":outlook_connected,"auto_send":False,
            "scheduled_delivery":False,"verified_health_monitoring":False,
            "notice":"Snapshot from authorized owner records only. No automatic sending, email inspection, market feed or claimed background execution.",
        })


class JarvisChiefDailyReviewView(APIView):
    """Idempotent, owner-scoped task reconciliation on explicit briefing start."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        from personal_calendar.models import PersonalCalendarEvent, PersonalCalendarEventAudit
        from django.contrib.auth import get_user_model
        from datetime import timedelta
        from zoneinfo import ZoneInfo
        from .assistant_daily_state import _finance_state, _health_state
        now = timezone.now()
        today = now.astimezone(ZoneInfo("America/Chicago")).date()
        money = _finance_state(request.user, today)
        health = _health_state(request.user)
        proposals = []
        for bill in money.get("due_next_7_days", []):
            amount = bill.get("amount")
            title = "Review " + str(bill["name"]) + (" payment of $" + format(amount, ",.2f") if amount is not None else " payment") + " due " + bill["due_date"]
            proposals.append(("bill:"+bill["type"]+":"+str(bill["id"])+":"+bill["due_date"], title, "/customer/finance", bill["due_date"]))
        if not (health.get("today") or {}).get("planned_workout"):
            proposals.append(("health:plan:"+today.isoformat(), "Set today's workout plan", "/customer/health", today.isoformat()))
        confirmed = request.data.get("completed_task_ids", [])
        if not isinstance(confirmed, list) or len(confirmed)>100 or any(not isinstance(i,int) or isinstance(i,bool) for i in confirmed):
            return Response({"detail":"Invalid task IDs."},status=400)
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            qs = PersonalCalendarEvent.objects.filter(owner=request.user,status="ACTIVE",metadata__entity_type="TASK")
            tasks = list(qs.select_for_update())
            keys = {str((t.metadata or {}).get("sydney_action_key")) for t in tasks}
            created = 0
            for key,title,url,due in proposals:
                if key in keys:
                    continue
                row = PersonalCalendarEvent.objects.create(owner=request.user,title=title[:180],start_at=now,end_at=now+timedelta(minutes=30),source="SYNC",created_by_sync=True,metadata={"entity_type":"TASK","task_status":"OPEN","task_unscheduled":True,"origin":"SYDNEY","sydney_action_key":key,"action_url":url,"due_date":due})
                PersonalCalendarEventAudit.objects.create(event=row,actor=request.user,action="CREATED",changes={"origin":"SYDNEY_DAILY_REVIEW"})
                tasks.append(row)
                keys.add(key)
                created += 1
            for row in tasks:
                meta = row.metadata or {}
                if meta.get("task_status","OPEN")!="OPEN":
                    continue
                key = str(meta.get("sydney_action_key",""))
                owner_confirmed = row.pk in confirmed
                workout_planned = key=="health:plan:"+today.isoformat() and bool((health.get("today") or {}).get("planned_workout"))
                if not (owner_confirmed or workout_planned):
                    continue
                evidence = "owner_confirmation" if owner_confirmed else "recorded_workout_plan"
                row.metadata = {**meta,"task_status":"DONE","completed_at":now.isoformat(),"completion_source":evidence}
                row.save(update_fields=["metadata","updated_at"])
                PersonalCalendarEventAudit.objects.create(event=row,actor=request.user,action="UPDATED",changes={"task_status":"DONE","completion_source":evidence})
        last = AuditLog.objects.filter(actor=request.user,action="sync_assist.chief.briefing_saved").order_by("-id").first()
        cutoff = last.created_at if last else now-timedelta(days=1)
        return Response({"created":created,"since":cutoff.isoformat(),"tasks":[{"id":t.pk,"title":t.title,"status":(t.metadata or {}).get("task_status","OPEN"),"url":(t.metadata or {}).get("action_url"),"note":(t.metadata or {}).get("task_note",""),"due_date":(t.metadata or {}).get("due_date"),"recently_completed":(t.metadata or {}).get("task_status")=="DONE" and t.updated_at>=cutoff} for t in tasks],"scope":"Recorded obligations and workout planning; no payments or completed workouts inferred."})


class JarvisChiefArchiveView(APIView):
    """Owner-only saved written briefing, with bounded retention by count."""
    permission_classes = [IsAuthenticated]
    action = "sync_assist.chief.briefing_saved"

    def get(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        rows = AuditLog.objects.filter(actor=request.user, action=self.action).order_by("-id")[:90]
        return Response({"briefings": [{"id": row.pk, "saved_at": row.created_at.isoformat(), **(row.metadata or {})} for row in rows]})

    def post(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        text = request.data.get("text")
        generated = request.data.get("generated_at")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 16000 or not isinstance(generated, str) or not 1 <= len(generated) <= 80:
            return Response({"detail": "Valid briefing text and timestamp required."}, status=400)
        with transaction.atomic():
            from django.contrib.auth import get_user_model
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            existing = AuditLog.objects.filter(actor=request.user, action=self.action, metadata__generated_at=generated).first()
            if existing:
                return Response({"id": existing.pk, "created": False})
            row = AuditLog.objects.create(actor=request.user, action=self.action,
                metadata={"text": text.strip(), "generated_at": generated, "source": "owner_saved_displayed_briefing"})
        return Response({"id": row.pk, "created": True}, status=201)


class JarvisChiefScheduleView(APIView):
    """Private, deterministic weekly planner. Preview is read-only; apply rechecks conflicts."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _pilot(request.user):
            return Response({"detail": "Private pilot only."}, status=403)
        from datetime import datetime, time, timedelta
        from zoneinfo import ZoneInfo
        from django.contrib.auth import get_user_model
        from django.db.models import Q
        from personal_calendar.models import PersonalCalendarEvent, PersonalCalendarEventAudit
        from .assistant_daily_state import _finance_state, _health_state, _tz
        from .jarvis_product import load_profile
        mode = request.data.get("mode", "preview")
        if mode not in {"preview", "apply", "auto"}:
            return Response({"detail":"Invalid mode."},status=400)
        _, profile = load_profile(request.user)
        tz = _tz(profile)
        now = timezone.now().astimezone(tz)
        today = now.date()
        end = datetime.combine(today+timedelta(days=7),time.min,tzinfo=tz)
        money = _finance_state(request.user,today)
        health = _health_state(request.user)
        def plan():
            records = PersonalCalendarEvent.objects.filter(owner=request.user,status="ACTIVE")
            events = list(records.filter(start_at__lt=end).filter(Q(end_at__gt=now)|Q(end_at__isnull=True,start_at__gte=now)).exclude(metadata__entity_type__in=["TASK","PROJECT"]).exclude(metadata__task_unscheduled=True).order_by("start_at"))
            tasks = list(records.filter(metadata__entity_type="TASK").exclude(metadata__task_status="DONE").order_by("id")[:100])
            busy = [(e.start_at,e.end_at or e.start_at+timedelta(minutes=30)) for e in events]
            keys = set(PersonalCalendarEvent.objects.filter(owner=request.user,metadata__sydney_plan_key__isnull=False).values_list("metadata__sydney_plan_key",flat=True))
            proposed, skipped = [], []
            def slot(day,hour,minute,duration,title,url,category,key):
                if key in keys:
                    return
                start = datetime.combine(day,time(hour,minute),tzinfo=tz)
                finish = start+timedelta(minutes=duration)
                if start<now:
                    return
                if any(start<b and finish>a for a,b in busy):
                    skipped.append({"title":title,"date":day.isoformat(),"reason":"Conflicts with an existing or proposed event"})
                    return
                busy.append((start,finish))
                proposed.append({"key":key,"title":title,"start_at":start.isoformat(),"end_at":finish.isoformat(),"url":url,"category":category})
            for offset in range(7):
                day=today+timedelta(days=offset)
                prefix=day.isoformat()+":"
                slot(day,6,30,20,"Sydney morning review","/customer","planning",prefix+"review")
                slot(day,9,0,60,"Health — workout or recovery plan","/customer/health","health",prefix+"health")
                if day.weekday()<5:
                    slot(day,12,30,120,"SyncWorks — focused development","/customer/projects","development",prefix+"build")
                    slot(day,14,30,30,"Review employee work and leads","/sync/assist/assignments","business",prefix+"employees")
                slot(day,18,0,20,"Daily progress and tomorrow's priorities","/customer","planning",prefix+"evening")
            day=today+timedelta(days=(5-today.weekday())%7)
            slot(day,11,0,45,"Plan groceries and meals","/customer/health","personal",day.isoformat()+":groceries")
            slot(day,12,0,30,"Review property obligations and Sarah's follow-ups","/pm/properties","property",day.isoformat()+":property")
            for offset in range(7):
                day=today+timedelta(days=offset)
                due=[b for b in money.get("due_next_7_days",[]) if b["due_date"]<=day.isoformat() and (offset==0 or b["due_date"]==day.isoformat())]
                if due:
                    slot(day,10,15,20,"Review recorded bills due","/customer/finance","finance",day.isoformat()+":bills")
            return proposed,skipped,[{"id":e.id,"title":e.title,"start_at":e.start_at.isoformat(),"end_at":e.end_at.isoformat() if e.end_at else None} for e in events],[{"id":t.id,"title":t.title,"note":(t.metadata or {}).get("task_note","")} for t in tasks]
        created=[]
        if mode in {"apply","auto"}:
            approved=request.data.get("approved_keys")
            if mode=="apply" and (not isinstance(approved,list) or len(approved)>100 or any(not isinstance(k,str) for k in approved)):
                return Response({"detail":"Approved schedule keys required."},status=400)
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=request.user.pk)
                proposed,skipped,existing,tasks=plan()
                for item in proposed:
                    if mode=="apply" and item["key"] not in approved:
                        continue
                    row=PersonalCalendarEvent.objects.create(owner=request.user,title=item["title"],start_at=datetime.fromisoformat(item["start_at"]),end_at=datetime.fromisoformat(item["end_at"]),timezone=str(tz),source="SYNC",created_by_sync=True,metadata={"sydney_plan_key":item["key"],"action_url":item["url"],"deep_link":item["url"],"fixed":False,"category":item["category"],"origin":"SYDNEY_WEEKLY_PLAN"})
                    PersonalCalendarEventAudit.objects.create(event=row,actor=request.user,action="CREATED",changes={"origin":"SYDNEY_WEEKLY_PLAN"})
                    created.append(row.pk)
                proposed,skipped,existing,tasks=plan()
        else:
            proposed,skipped,existing,tasks=plan()
        return Response({"mode":mode,"timezone":str(tz),"proposed":proposed,"skipped":skipped,"existing":existing,"tasks":tasks,"created_ids":created,"workout_plan_recorded":bool((health.get("today") or {}).get("planned_workout")),"scope":"Proposed routine blocks only; existing appointments unchanged. No workout, grocery purchase, payment or development completion is inferred."})
