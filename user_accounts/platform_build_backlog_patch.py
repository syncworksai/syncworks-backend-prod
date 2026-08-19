from __future__ import annotations

import json
import os
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from rest_framework import status
from rest_framework.response import Response

from user_accounts.viewsets.platform_console import (
    PlatformDeveloperAgentRunAPIView,
    PlatformDeveloperAgentStatusAPIView,
)

BACKLOG_REPOSITORY = os.getenv("SYNCWORKS_BUILD_BACKLOG_REPOSITORY") or "syncworksai/Syncworks-developer-agent"
BACKLOG_MARKER = "<!-- SYNCWORKS_BUILD_BACKLOG -->"
BACKLOG_TITLE_PREFIX = "[SYNC BACKLOG]"
BACKLOG_STATUSES = {"IDEA", "BUILD_LATER", "NEXT", "IN_PROGRESS", "TESTING", "DONE"}
BACKLOG_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "URGENT"}


def _token():
    return os.getenv("SYNCWORKS_BUILD_BACKLOG_TOKEN") or os.getenv("SYNCWORKS_DEVELOPER_AGENT_TOKEN") or ""


def _headers(token, *, json_body=False):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "syncworks-god-mode-build-backlog",
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _api(path, *, method="GET", payload=None):
    token = _token()
    if not token:
        raise RuntimeError("Build Backlog token is not configured.")
    url = f"https://api.github.com/repos/{BACKLOG_REPOSITORY}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=data, headers=_headers(token, json_body=payload is not None), method=method)
    with urlopen(request, timeout=12) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _metadata_from_body(body):
    text = str(body or "")
    if BACKLOG_MARKER not in text:
        return None
    before_notes, _, notes = text.partition("\n---\n")
    metadata = {}
    for line in before_notes.splitlines():
        if ":" not in line or line.strip().startswith("<!--"):
            continue
        key, value = line.split(":", 1)
        metadata[key.strip().lower().replace(" ", "_")] = value.strip()
    metadata["notes"] = notes.strip()
    return metadata


def _build_body(*, status_value, priority, module, source, notes, created=None):
    return (
        f"{BACKLOG_MARKER}\n"
        f"Status: {status_value}\n"
        f"Priority: {priority}\n"
        f"Module: {module}\n"
        f"Source: {source}\n"
        f"Created: {created or date.today().isoformat()}\n\n"
        f"---\n{notes.strip()}\n"
    )


def _item(issue):
    metadata = _metadata_from_body(issue.get("body"))
    if metadata is None:
        return None
    title = str(issue.get("title") or "")
    if title.startswith(BACKLOG_TITLE_PREFIX):
        title = title[len(BACKLOG_TITLE_PREFIX):].strip()
    status_value = str(metadata.get("status") or ("DONE" if issue.get("state") == "closed" else "BUILD_LATER")).upper()
    if status_value not in BACKLOG_STATUSES:
        status_value = "BUILD_LATER"
    priority = str(metadata.get("priority") or "MEDIUM").upper()
    if priority not in BACKLOG_PRIORITIES:
        priority = "MEDIUM"
    return {
        "id": issue.get("number"),
        "issue_number": issue.get("number"),
        "title": title,
        "status": status_value,
        "priority": priority,
        "module": metadata.get("module") or "General",
        "source": metadata.get("source") or "God Mode",
        "created": metadata.get("created") or str(issue.get("created_at") or "")[:10],
        "notes": metadata.get("notes") or "",
        "url": issue.get("html_url") or "",
        "github_state": issue.get("state") or "open",
        "updated_at": issue.get("updated_at") or "",
    }


def _list_items():
    params = urlencode({"state": "all", "per_page": 100, "sort": "updated", "direction": "desc"})
    rows = _api(f"/issues?{params}")
    items = []
    for issue in rows if isinstance(rows, list) else []:
        if issue.get("pull_request"):
            continue
        item = _item(issue)
        if item:
            items.append(item)
    return items


def _create_item(data):
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("Title is required.")
    status_value = str(data.get("status") or "BUILD_LATER").strip().upper()
    priority = str(data.get("priority") or "MEDIUM").strip().upper()
    if status_value not in BACKLOG_STATUSES:
        raise ValueError("Invalid backlog status.")
    if priority not in BACKLOG_PRIORITIES:
        raise ValueError("Invalid backlog priority.")
    body = _build_body(
        status_value=status_value,
        priority=priority,
        module=str(data.get("module") or "General").strip() or "General",
        source=str(data.get("source") or "God Mode").strip() or "God Mode",
        notes=str(data.get("notes") or "").strip(),
    )
    issue = _api("/issues", method="POST", payload={"title": f"{BACKLOG_TITLE_PREFIX} {title}", "body": body})
    return _item(issue)


def _update_item(data):
    issue_number = int(data.get("issue_number") or data.get("id") or 0)
    if issue_number <= 0:
        raise ValueError("Issue number is required.")
    current = _api(f"/issues/{issue_number}")
    current_item = _item(current)
    if not current_item:
        raise ValueError("This GitHub issue is not a SyncWorks backlog item.")
    title = str(data.get("title") or current_item["title"]).strip()
    status_value = str(data.get("status") or current_item["status"]).strip().upper()
    priority = str(data.get("priority") or current_item["priority"]).strip().upper()
    if status_value not in BACKLOG_STATUSES:
        raise ValueError("Invalid backlog status.")
    if priority not in BACKLOG_PRIORITIES:
        raise ValueError("Invalid backlog priority.")
    body = _build_body(
        status_value=status_value,
        priority=priority,
        module=str(data.get("module") or current_item["module"]).strip() or "General",
        source=str(data.get("source") or current_item["source"]).strip() or "God Mode",
        notes=str(data.get("notes") if "notes" in data else current_item["notes"]),
        created=current_item["created"],
    )
    issue = _api(
        f"/issues/{issue_number}",
        method="PATCH",
        payload={
            "title": f"{BACKLOG_TITLE_PREFIX} {title}",
            "body": body,
            "state": "closed" if status_value == "DONE" else "open",
        },
    )
    return _item(issue)


_original_status_get = PlatformDeveloperAgentStatusAPIView.get
_original_run_post = PlatformDeveloperAgentRunAPIView.post


def _status_get(self, request):
    response = _original_status_get(self, request)
    if not isinstance(getattr(response, "data", None), dict):
        return response
    payload = dict(response.data)
    payload["build_backlog"] = {
        "configured": bool(_token()),
        "repository": BACKLOG_REPOSITORY,
        "statuses": sorted(BACKLOG_STATUSES),
        "priorities": ["URGENT", "HIGH", "MEDIUM", "LOW"],
        "items": [],
        "error": "",
    }
    if _token():
        try:
            payload["build_backlog"]["items"] = _list_items()
        except Exception as exc:
            payload["build_backlog"]["error"] = str(exc)[:300]
    response.data = payload
    return response


def _run_post(self, request):
    action = str(request.data.get("backlog_action") or "").strip().lower()
    if not action:
        return _original_run_post(self, request)
    try:
        if action == "create":
            item = _create_item(request.data)
            return Response({"detail": "Backlog item created.", "item": item}, status=status.HTTP_201_CREATED)
        if action == "update":
            item = _update_item(request.data)
            return Response({"detail": "Backlog item updated.", "item": item})
        return Response({"detail": "Unsupported backlog action."}, status=status.HTTP_400_BAD_REQUEST)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except RuntimeError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except HTTPError as exc:
        return Response({"detail": "GitHub backlog request failed.", "status_code": exc.code}, status=status.HTTP_502_BAD_GATEWAY)
    except URLError:
        return Response({"detail": "Unable to reach the GitHub backlog repository."}, status=status.HTTP_502_BAD_GATEWAY)
    except Exception:
        return Response({"detail": "Unexpected Build Backlog error."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


PlatformDeveloperAgentStatusAPIView.get = _status_get
PlatformDeveloperAgentRunAPIView.post = _run_post
