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
        cfg=_settings()
        outlook_connected=bool(cfg and _latest(request.user))
        sections=[
            {"key":"today","title":"Today","headline":f"{len(tasks)} open tasks, {len(high)} high priority","items":[
                {"title":x["title"],"source":x["source"],"category":x["category"],"next_action":x["action"]}
                for x in tasks[:3]],"scope":"Owner tasks and selected SyncWorks records"},
            {"key":"cases","title":"Unresolved issues","headline":f"{len(open_cases)} unresolved case files ({len(priority_cases)} high priority)","items":[
                {"title":x["title"],"source":"owner_entered","category":x["category"],"next_action":x["next_step"] or "Review case"}
                for x in open_cases[:3]],"scope":"Cases manually entered or updated by account owner"},
            {"key":"portfolio","title":"Business & properties","headline":f"{daily['data_diagnostics']['owned_businesses']} owned businesses, {daily['data_diagnostics']['owned_properties']} linked properties","items":[],"scope":daily["data_diagnostics"]["scan_limit"]},
            {"key":"email","title":"Email","headline":"Outlook connected; open Mail Desk for an on-demand inbox brief" if outlook_connected else "Outlook is not connected inside SyncWorks","items":[],"scope":"No email content included in this briefing"},
        ]
        return Response({
            "date":daily["date"],"generated_at":timezone.now().isoformat(),"mode":"on_demand",
            "sections":sections,"counts":{
                "tasks_open":len(tasks),"tasks_high":len(high),
                "cases_open":len(open_cases),"cases_high":len(priority_cases),
            },"outlook_connected":outlook_connected,"auto_send":False,
            "scheduled_delivery":False,"verified_health_monitoring":False,
            "notice":"Snapshot from authorized owner records only. No automatic sending, email inspection, market feed or claimed background execution.",
        })
