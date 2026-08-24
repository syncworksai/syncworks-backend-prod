from __future__ import annotations

import json
import os
from datetime import date
from urllib.request import Request, urlopen

from rest_framework import status
from rest_framework.response import Response

from user_accounts.models.platform_build_backlog import PlatformBuildBacklogItem
from user_accounts.viewsets.platform_console import PlatformDeveloperAgentRunAPIView, PlatformDeveloperAgentStatusAPIView

BACKLOG_REPOSITORY = os.getenv("SYNCWORKS_BUILD_BACKLOG_REPOSITORY") or "syncworksai/Syncworks-developer-agent"
BACKLOG_MARKER = "<!-- SYNCWORKS_BUILD_BACKLOG -->"
BACKLOG_TITLE_PREFIX = "[SYNC BACKLOG]"
BACKLOG_STATUSES = {choice for choice, _ in PlatformBuildBacklogItem.Status.choices}
BACKLOG_PRIORITIES = {choice for choice, _ in PlatformBuildBacklogItem.Priority.choices}


def _token():
    return os.getenv("SYNCWORKS_BUILD_BACKLOG_TOKEN") or os.getenv("SYNCWORKS_DEVELOPER_AGENT_TOKEN") or ""


def _headers(token, *, json_body=False):
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "syncworks-god-mode-build-backlog"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _github_api(path, *, method="GET", payload=None):
    token = _token()
    if not token:
        raise RuntimeError("GitHub mirror token is not configured.")
    url = f"https://api.github.com/repos/{BACKLOG_REPOSITORY}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=data, headers=_headers(token, json_body=payload is not None), method=method)
    with urlopen(request, timeout=12) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _build_body(item):
    return f"{BACKLOG_MARKER}\nStatus: {item.status}\nPriority: {item.priority}\nModule: {item.module}\nSource: {item.source}\nCreated: {item.created_at.date().isoformat() if item.created_at else date.today().isoformat()}\n\n---\n{item.notes.strip()}\n"


def _serialize(item):
    return {
        "id": item.id,
        "issue_number": item.github_issue_number or item.id,
        "title": item.title,
        "status": item.status,
        "priority": item.priority,
        "module": item.module or "General",
        "source": item.source or "God Mode",
        "created": item.created_at.date().isoformat() if item.created_at else "",
        "notes": item.notes or "",
        "url": item.github_url or "",
        "github_state": "closed" if item.status == PlatformBuildBacklogItem.Status.DONE else "open",
        "updated_at": item.updated_at.isoformat() if item.updated_at else "",
        "github_mirrored": bool(item.github_issue_number),
        "github_sync_error": item.github_sync_error or "",
    }


def _mirror_create(item):
    if not _token():
        return
    try:
        issue = _github_api("/issues", method="POST", payload={"title": f"{BACKLOG_TITLE_PREFIX} {item.title}", "body": _build_body(item)})
        item.github_issue_number = issue.get("number")
        item.github_url = issue.get("html_url") or ""
        item.github_sync_error = ""
        item.save(update_fields=["github_issue_number", "github_url", "github_sync_error", "updated_at"])
    except Exception as exc:
        item.github_sync_error = f"GitHub mirror unavailable: {exc}"[:300]
        item.save(update_fields=["github_sync_error", "updated_at"])


def _mirror_update(item):
    if not _token() or not item.github_issue_number:
        return
    try:
        issue = _github_api(f"/issues/{item.github_issue_number}", method="PATCH", payload={"title": f"{BACKLOG_TITLE_PREFIX} {item.title}", "body": _build_body(item), "state": "closed" if item.status == PlatformBuildBacklogItem.Status.DONE else "open"})
        item.github_url = issue.get("html_url") or item.github_url
        item.github_sync_error = ""
        item.save(update_fields=["github_url", "github_sync_error", "updated_at"])
    except Exception as exc:
        item.github_sync_error = f"GitHub mirror unavailable: {exc}"[:300]
        item.save(update_fields=["github_sync_error", "updated_at"])


def _validate(data):
    title = str(data.get("title") or "").strip()
    status_value = str(data.get("status") or "BUILD_LATER").strip().upper()
    priority = str(data.get("priority") or "MEDIUM").strip().upper()
    if not title:
        raise ValueError("Title is required.")
    if status_value not in BACKLOG_STATUSES:
        raise ValueError("Invalid backlog status.")
    if priority not in BACKLOG_PRIORITIES:
        raise ValueError("Invalid backlog priority.")
    return title, status_value, priority


def _create_item(data, user):
    title, status_value, priority = _validate(data)
    item = PlatformBuildBacklogItem.objects.create(title=title, status=status_value, priority=priority, module=str(data.get("module") or "General").strip() or "General", source=str(data.get("source") or "God Mode").strip() or "God Mode", notes=str(data.get("notes") or "").strip(), created_by=user, updated_by=user)
    _mirror_create(item)
    return item


def _update_item(data, user):
    raw_id = int(data.get("id") or data.get("issue_number") or 0)
    item = PlatformBuildBacklogItem.objects.filter(id=raw_id).first()
    if item is None:
        item = PlatformBuildBacklogItem.objects.filter(github_issue_number=raw_id).first()
    if item is None:
        raise ValueError("Backlog item not found.")
    title, status_value, priority = _validate({"title": data.get("title") or item.title, "status": data.get("status") or item.status, "priority": data.get("priority") or item.priority})
    item.title = title
    item.status = status_value
    item.priority = priority
    item.module = str(data.get("module") or item.module or "General").strip() or "General"
    item.source = str(data.get("source") or item.source or "God Mode").strip() or "God Mode"
    if "notes" in data:
        item.notes = str(data.get("notes") or "")
    item.updated_by = user
    item.save()
    _mirror_update(item)
    return item


_original_status_get = PlatformDeveloperAgentStatusAPIView.get
_original_run_post = PlatformDeveloperAgentRunAPIView.post


def _status_get(self, request):
    response = _original_status_get(self, request)
    if not isinstance(getattr(response, "data", None), dict):
        return response
    payload = dict(response.data)
    items = [_serialize(item) for item in PlatformBuildBacklogItem.objects.all()[:500]]
    mirror_errors = [item["github_sync_error"] for item in items if item.get("github_sync_error")]
    payload["build_backlog"] = {
        "configured": True,
        "storage": "SYNCWORKS_DATABASE",
        "repository": BACKLOG_REPOSITORY,
        "github_mirror_configured": bool(_token()),
        "github_mirror_healthy": not bool(mirror_errors),
        "statuses": sorted(BACKLOG_STATUSES),
        "priorities": ["URGENT", "HIGH", "MEDIUM", "LOW"],
        "items": items,
        "error": "",
        "warning": mirror_errors[0] if mirror_errors else "",
    }
    response.data = payload
    return response


def _run_post(self, request):
    action = str(request.data.get("backlog_action") or "").strip().lower()
    if not action:
        return _original_run_post(self, request)
    try:
        if action == "create":
            item = _create_item(request.data, request.user)
            return Response({"detail": "Backlog item created in SyncWorks.", "item": _serialize(item)}, status=status.HTTP_201_CREATED)
        if action == "update":
            item = _update_item(request.data, request.user)
            return Response({"detail": "Backlog item updated in SyncWorks.", "item": _serialize(item)})
        return Response({"detail": "Unsupported backlog action."}, status=status.HTTP_400_BAD_REQUEST)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception:
        return Response({"detail": "Unexpected Build Backlog error."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


PlatformDeveloperAgentStatusAPIView.get = _status_get
PlatformDeveloperAgentRunAPIView.post = _run_post
