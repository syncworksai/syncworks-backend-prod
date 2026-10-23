"""Workspace staff: explicit membership, property-specific assignments, task-only access."""
import hashlib
import secrets
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .access_models import PMWorkspaceStaff, PMStaffTask
from .models import PMWorkspace, PMProperty

CAPS={
 "MANAGER":{"onboarding","evictions","maintenance","documents","communications","accounting","inspections","general"},
 "LEASING":{"onboarding","documents","communications","general"},
 "EVICTIONS":{"evictions","documents","communications"},
 "MAINTENANCE":{"maintenance","inspections","general"},
 "ACCOUNTING":{"accounting","general"},
 "DOCUMENTS":{"documents","onboarding","communications"},
 "VIEW_ONLY":set(),
}
CATEGORIES={"ONBOARDING":"onboarding","EVICTIONS":"evictions","MAINTENANCE":"maintenance",
 "DOCUMENTS":"documents","COMMUNICATIONS":"communications","ACCOUNTING":"accounting",
 "INSPECTIONS":"inspections","GENERAL":"general"}

def _owner(request):
 qs=PMWorkspace.objects.filter(owner=request.user,is_active=True)
 wid=request.headers.get("X-PM-Workspace-ID")
 ws=qs.filter(pk=wid).first() if wid else qs.first()
 if not ws:raise PermissionDenied("Portfolio owner access required.")
 return ws

def _member(request):
 q=PMWorkspaceStaff.objects.filter(user=request.user,status="ACTIVE",workspace__is_active=True)
 wid=request.headers.get("X-PM-Workspace-ID")
 return q.filter(workspace_id=wid).first() if wid else q.first()

def _property_ids(ws,values):
 if not isinstance(values,list) or len(values)>250:raise ValueError("Choose up to 250 assigned properties.")
 try:ids=sorted({int(v) for v in values})
 except (ValueError,TypeError):raise ValueError("Invalid property selection.")
 if PMProperty.objects.filter(workspace=ws,id__in=ids).count()!=len(ids):
  raise ValueError("Each property must be in your portfolio.")
 return ids

def _permitted(member,category):
 cap=CATEGORIES.get(category)
 return bool(cap and cap in CAPS.get(member.role,set()) and cap in (member.permissions or []))

def _staff_json(x):
 return {"id":x.id,"name":x.name,"email":x.email,"role":x.role,"status":x.status,
         "permissions":x.permissions,"property_ids":list(x.properties.values_list("id",flat=True))}

def _task_json(t):
 return {"id":t.id,"title":t.title,"category":t.category,"status":t.status,
         "property_id":t.property_id,"property_name":t.property.name,"assignee_id":t.assignee_id,
         "notes":t.notes,"due_date":t.due_date.isoformat() if t.due_date else None}

@api_view(["GET","POST"])
@permission_classes([IsAuthenticated])
def owner_staff(request):
 ws=_owner(request)
 if request.method=="GET":
  return Response({"members":[_staff_json(x) for x in PMWorkspaceStaff.objects.filter(workspace=ws)],
                   "roles":{k:sorted(v) for k,v in CAPS.items()}})
 email=str(request.data.get("email") or "").strip().casefold()
 role=str(request.data.get("role") or "VIEW_ONLY").upper()
 if "@" not in email or role not in CAPS:return Response({"detail":"Valid email and role required."},status=400)
 if PMWorkspaceStaff.objects.filter(workspace=ws,email__iexact=email).exclude(status="REVOKED").exists():
  return Response({"detail":"Employee already exists or has a pending invitation."},status=409)
 try:
  ids=_property_ids(ws,request.data.get("property_ids") or [])
  requested=request.data.get("permissions",sorted(CAPS[role]))
  if not isinstance(requested,list) or any(p not in CAPS[role] for p in requested):
   raise ValueError("Permissions exceed role limits.")
 except ValueError as exc:return Response({"detail":str(exc)},status=400)
 code=secrets.token_urlsafe(28)
 x,_=PMWorkspaceStaff.objects.update_or_create(workspace=ws,email=email,defaults={
  "name":str(request.data.get("name") or "")[:180],"role":role,
  "permissions":sorted(set(requested)),"status":"INVITED","user":None,
  "invite_token_hash":hashlib.sha256(code.encode()).hexdigest(),
  "invite_expires_at":timezone.now()+timedelta(days=14),"accepted_at":None})
 x.properties.set(ids)
 return Response({"member":_staff_json(x),"invitation_code":code,
                  "detail":"Invitation prepared; securely share with the employee. No email sent."},status=201)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def accept_staff(request):
 code=str(request.data.get("code") or "")
 if len(code)<24:return Response({"detail":"Invalid invitation."},status=400)
 token_hash=hashlib.sha256(code.encode()).hexdigest()
 with transaction.atomic():
  x=PMWorkspaceStaff.objects.select_for_update().filter(
   invite_token_hash=token_hash,status="INVITED",invite_expires_at__gt=timezone.now()).first()
  if not x:return Response({"detail":"Invitation expired or invalid."},status=404)
  if str(request.user.email or "").casefold()!=x.email.casefold():
   return Response({"detail":"Sign in using the invited email."},status=403)
  x.user=request.user;x.status="ACTIVE";x.invite_token_hash="";x.accepted_at=timezone.now()
  x.save(update_fields=["user","status","invite_token_hash","accepted_at","updated_at"])
 return Response({"member":_staff_json(x)})

@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_staff(request,member_id):
 ws=_owner(request)
 x=PMWorkspaceStaff.objects.filter(workspace=ws,pk=member_id).first()
 if not x:return Response({"detail":"Staff member not found."},status=404)
 role=str(request.data.get("role",x.role)).upper()
 if role not in CAPS:return Response({"detail":"Invalid role."},status=400)
 perms=request.data.get("permissions",x.permissions)
 if not isinstance(perms,list) or any(p not in CAPS[role] for p in perms):
  return Response({"detail":"Permissions exceed role limits."},status=400)
 try:ids=_property_ids(ws,request.data.get("property_ids",list(x.properties.values_list("id",flat=True))))
 except ValueError as exc:return Response({"detail":str(exc)},status=400)
 state=str(request.data.get("status",x.status)).upper()
 if state=="ACTIVE" and x.status!="ACTIVE":
  return Response({"detail":"Only employee acceptance can activate an invitation."},status=409)
 if state not in ("INVITED","ACTIVE","REVOKED"):
  return Response({"detail":"Invalid status."},status=400)
 x.role=role;x.permissions=sorted(set(perms));x.status=state
 if state=="REVOKED":x.invite_token_hash="";x.user=None
 x.save(update_fields=["role","permissions","status","invite_token_hash","user","updated_at"])
 x.properties.set(ids)
 return Response({"member":_staff_json(x)})

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def employee_dashboard(request):
 x=_member(request)
 if not x:return Response({"detail":"No active property management staff access."},status=403)
 ids=list(x.properties.values_list("id",flat=True))
 tasks=[t for t in PMStaffTask.objects.filter(workspace=x.workspace,assignee=x,
         property_id__in=ids).select_related("property") if _permitted(x,t.category)]
 return Response({"workspace":{"id":x.workspace_id,"name":x.workspace.name},"role":x.role,
                  "permissions":x.permissions,"properties":list(PMProperty.objects.filter(
                    id__in=ids,workspace=x.workspace).values("id","name","address")),
                  "tasks":[_task_json(t) for t in tasks[:150]],
                  "open":sum(t.status not in ("DONE","CANCELED") for t in tasks),
                  "finance_access":False})

@api_view(["GET","POST"])
@permission_classes([IsAuthenticated])
def owner_tasks(request):
 ws=_owner(request)
 if request.method=="GET":
  return Response({"tasks":[_task_json(t) for t in PMStaffTask.objects.filter(
     workspace=ws).select_related("property")[:300]]})
 prop=PMProperty.objects.filter(workspace=ws,id=request.data.get("property_id")).first()
 category=str(request.data.get("category") or "").upper()
 title=str(request.data.get("title") or "").strip()[:180]
 if not prop or category not in CATEGORIES or not title:
  return Response({"detail":"Property, category and title are required."},status=400)
 assigned=request.data.get("assignee_id") or None
 x=PMWorkspaceStaff.objects.filter(workspace=ws,id=assigned,status="ACTIVE").first() if assigned else None
 if assigned and not x:return Response({"detail":"Assigned staff member not active."},status=400)
 if x and (not x.properties.filter(id=prop.id).exists() or not _permitted(x,category)):
  return Response({"detail":"Staff member lacks this property or task permission."},status=403)
 try:due=date.fromisoformat(str(request.data["due_date"])) if request.data.get("due_date") else None
 except ValueError:return Response({"detail":"Invalid due date."},status=400)
 t=PMStaffTask.objects.create(workspace=ws,property=prop,category=category,title=title,
     assignee=x,notes=str(request.data.get("notes") or "")[:2000],due_date=due,created_by=request.user)
 return Response({"task":_task_json(t)},status=201)

@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def task_status(request,task_id):
 x=None
 try:ws=_owner(request);owner=True
 except PermissionDenied:
  x=_member(request);owner=False
  if not x:return Response({"detail":"Staff access required."},status=403)
  ws=x.workspace
 t=PMStaffTask.objects.filter(workspace=ws,pk=task_id).select_related("property").first()
 if not t:return Response({"detail":"Task not found."},status=404)
 if not owner and (t.assignee_id!=x.id or not x.properties.filter(id=t.property_id).exists() or
                   not _permitted(x,t.category)):
  return Response({"detail":"Task is not assigned to you."},status=403)
 state=str(request.data.get("status") or "").upper()
 if state not in PMStaffTask.Status.values:return Response({"detail":"Invalid task status."},status=400)
 if t.category=="EVICTIONS" and state=="DONE" and not owner:state="REVIEW"
 t.status=state;t.completed_at=timezone.now() if state=="DONE" else None
 t.save(update_fields=["status","completed_at","updated_at"])
 return Response({"task":_task_json(t)})
