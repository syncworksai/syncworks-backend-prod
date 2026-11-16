"""Founder-only freelance pilot API.

This deliberately uses owner-scoped AuditLog events for small project metadata
and processes CSV in memory. Client files, cleaned contents and AI prompts are
never written to AuditLog, MEDIA_ROOT or any object storage.

No automatic Upwork access, external delivery, scheduling or autonomous AI execution.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import math
import os
from uuid import UUID, uuid4

from django.db import transaction
from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from user_accounts.models import AuditLog
from .assist_pilot_views import _pilot
from .service import (
    SyncAIConfigurationError, SyncAIProviderError, create_sync_response,
)

EVENT_ADD = "freelance.pilot.project.created"
EVENT_UPDATE = "freelance.pilot.project.updated"
MAX_PROJECTS = 100
MAX_BYTES = 512 * 1024
MAX_ROWS = 5000
MAX_COLUMNS = 80
ALLOWED_STATUSES = {
    "Saved", "Proposal drafted", "Applied", "Interview",
    "Contracted", "In progress", "Submitted", "Paid", "Declined",
}


def _founder_authorized(user):
    # Fail closed until operators pin the verified founder's immutable user id.
    configured = str(getattr(settings, 'FREELANCE_PILOT_USER_ID', '') or os.getenv('FREELANCE_PILOT_USER_ID', '')).strip()
    return bool(configured and _pilot(user) and user.email_verified and str(user.pk) == configured)


class FounderFreelancePermission(BasePermission):
    def has_permission(self, request, view):
        return _founder_authorized(request.user)


class FreelanceThrottle(UserRateThrottle):
    scope = "freelance_pilot"

    def get_rate(self):
        return "30/hour"


class FreelanceAIThrottle(UserRateThrottle):
    scope = "freelance_ai_pilot"

    def get_rate(self):
        return "5/hour"


def _snapshot(user):
    records = {}
    for event in AuditLog.objects.filter(
        actor=user, action__in=[EVENT_ADD, EVENT_UPDATE],
    ).order_by("id").only("action", "metadata", "created_at"):
        metadata = event.metadata or {}
        project_id = metadata.get("project_id", "")
        try:
            project_id = str(UUID(str(project_id)))
        except ValueError:
            continue
        if event.action == EVENT_ADD:
            if project_id not in records:
                records[project_id] = {
                    "id": project_id, "created_at": event.created_at.isoformat(),
                    "updated_at": event.created_at.isoformat(),
                    **metadata.get("fields", {}),
                }
        elif project_id in records:
            records[project_id].update(metadata.get("fields", {}))
            records[project_id]["updated_at"] = event.created_at.isoformat()
    return sorted(records.values(), key=lambda x: x["created_at"], reverse=True)


def _fields(data, *, partial=False):
    allowed = {"title", "status", "budget", "platform", "type", "url", "deadline", "project_checks"}
    if not isinstance(data, dict):
        raise ValidationError("Project details must be an object.")
    if set(data.keys()) - allowed:
        raise ValidationError("Unexpected project fields.")
    fields = {}
    for field in allowed:
        if field not in data:
            continue
        value = data[field]
        if field == "project_checks":
            if not isinstance(value, list) or len(value) > 6 or any(type(i) is not int or i < 0 or i > 5 for i in value) or len(set(value)) != len(value):
                raise ValidationError({"project_checks": "Use unique checklist step indices from 0 to 5."})
            fields[field] = value
            continue
        if field == "budget":
            try:
                val = round(float(value), 2)
            except (ValueError, TypeError):
                raise ValidationError({"budget": "Expected a numeric amount."})
            if not math.isfinite(val) or val < 0 or val > 100000:
                raise ValidationError({"budget": "Value out of range."})
            fields[field] = val
            continue
        value = str(value or "").strip()
        if field == "status" and value not in ALLOWED_STATUSES:
            raise ValidationError({"status": "Unrecognized project status."})
        if len(value) > {"title": 150, "platform": 60, "type": 30, "url": 500, "deadline": 10, "status": 25}[field]:
            raise ValidationError({field: "Value too long."})
        if field == "url" and value and not value.startswith("https://"):
            raise ValidationError({"url": "Only HTTPS links are supported."})
        if field == "deadline" and value:
            from datetime import date
            try:
                date.fromisoformat(value)
            except ValueError:
                raise ValidationError({"deadline": "Use YYYY-MM-DD."})
        fields[field] = value
    if not partial and not fields.get("title"):
        raise ValidationError({"title": "A project title is required."})
    if partial and "title" in fields and not fields["title"]:
        raise ValidationError({"title": "A project title is required."})
    return fields


class FreelancePilotAccessView(APIView):
    permission_classes = [IsAuthenticated, FounderFreelancePermission]
    throttle_classes = [FreelanceThrottle]

    def get(self, request):
        return Response({
            "enabled": True, "account_id": request.user.pk,
            "capabilities": {
                "project_records": True, "csv_process": True,
                "jarvis_plan": True, "client_file_storage": False,
                "upwork_connection": False, "auto_delivery": False,
                "background_execution": False,
            },
            "notice": "Founder pilot; client files are not stored; external actions require manual approval.",
        })


class FreelanceProjectsView(APIView):
    permission_classes = [IsAuthenticated, FounderFreelancePermission]
    throttle_classes = [FreelanceThrottle]

    def get(self, request):
        return Response({"projects": _snapshot(request.user)})

    def post(self, request):
        fields = _fields(request.data)
        with transaction.atomic():
            user = type(request.user).objects.select_for_update().get(pk=request.user.pk)
            if len(_snapshot(user)) >= MAX_PROJECTS:
                return Response({"detail": "Project limit reached."}, status=429)
            project_id = str(uuid4())
            fields.setdefault("status", "Saved")
            AuditLog.objects.create(actor=user, action=EVENT_ADD, metadata={
                "project_id": project_id, "fields": fields,
            })
        return Response({"id": project_id, "projects": _snapshot(request.user)}, status=201)


class FreelanceProjectDetailView(APIView):
    permission_classes = [IsAuthenticated, FounderFreelancePermission]
    throttle_classes = [FreelanceThrottle]

    def patch(self, request, project_id):
        try:
            key = str(UUID(str(project_id)))
        except ValueError:
            return Response({"detail": "Invalid project id."}, status=400)
        fields = _fields(request.data, partial=True)
        if not fields:
            return Response({"detail": "No fields supplied."}, status=400)
        with transaction.atomic():
            user = type(request.user).objects.select_for_update().get(pk=request.user.pk)
            if not any(p["id"] == key for p in _snapshot(user)):
                return Response({"detail": "Project not found."}, status=404)
            AuditLog.objects.create(actor=user, action=EVENT_UPDATE, metadata={
                "project_id": key, "fields": fields,
            })
        return Response({"projects": _snapshot(request.user)})


def _clean_csv(payload, *, dedupe=True, lowercase_email=True, trim=True, drop_empty=True):
    try:
        content = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationError("CSV must use UTF-8.")
    try:
        rows = csv.reader(io.StringIO(content, newline=""), strict=True)
        header = next(rows)
        if not header or len(header) > MAX_COLUMNS:
            raise ValidationError("CSV must have 1 to 80 header columns.")
        columns = [h.strip() for h in header]
        if any(not h for h in columns) or len({h.lower() for h in columns}) != len(columns):
            raise ValidationError("CSV headers must be nonempty and unique.")
        cleaned, flagged, seen = [], [], set()
        removed_blank = removed_duplicate = updated_cells = 0
        count = 0
        for row in rows:
            count += 1
            if count > MAX_ROWS:
                raise ValidationError("Pilot CSV row limit is 5,000.")
            if len(row) != len(columns):
                flagged.append({"row": count + 1, "issue": "Unexpected column count"})
                continue
            normalized = []
            for idx, raw in enumerate(row):
                value = raw.strip() if trim else raw
                if lowercase_email and "email" in columns[idx].lower().replace("-", ""):
                    value = value.lower()
                if value != raw:
                    updated_cells += 1
                normalized.append(value)
            if drop_empty and not any(v.strip() for v in normalized):
                removed_blank += 1
                continue
            key = tuple(v.casefold() for v in normalized)
            if dedupe and key in seen:
                removed_duplicate += 1
                continue
            seen.add(key)
            cleaned.append(normalized)
    except csv.Error:
        raise ValidationError("Malformed CSV. Check quoting and delimiters.")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    # Protect exported CSV against spreadsheet formula injection.
    def safe(v):
        return "'" + v if v.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else v
    writer.writerow([safe(c) for c in columns])
    writer.writerows([[safe(v) for v in row] for row in cleaned])
    result = output.getvalue().encode("utf-8")
    return {
        "cleaned_csv_base64": base64.b64encode(result).decode("ascii"),
        "preview": [dict(zip(columns, row)) for row in cleaned[:5]],
        "report": {
            "source_rows": count, "cleaned_rows": len(cleaned),
            "duplicate_rows_removed": removed_duplicate,
            "empty_rows_removed": removed_blank,
            "normalized_cells": updated_cells,
            "flagged_rows": flagged[:100],
            "flagged_count": len(flagged),
            "sha256": hashlib.sha256(result).hexdigest(),
            "warning": "Rows with wrong column counts are excluded; review before delivering.",
        },
    }


class FreelanceCSVProcessView(APIView):
    permission_classes = [IsAuthenticated, FounderFreelancePermission]
    throttle_classes = [FreelanceThrottle]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            return Response({"detail": "CSV file required."}, status=400)
        if not upload.name.lower().endswith(".csv") or upload.size > MAX_BYTES:
            return Response({"detail": "Only UTF-8 CSV files up to 512 KB are supported."}, status=400)
        if upload.size <= 0:
            return Response({"detail": "File is empty."}, status=400)
        options = {key: str(request.data.get(key, "true")).lower() == "true"
                   for key in ("dedupe", "lowercase_email", "trim", "drop_empty")}
        try:
            outcome = _clean_csv(upload.read(MAX_BYTES + 1), **options)
        except (ValidationError, StopIteration) as exc:
            return Response({"detail": getattr(exc, "detail", str(exc))}, status=400)
        # Do not log source or cleaned data, filenames or AI prompts.
        AuditLog.objects.create(actor=request.user, action="freelance.pilot.csv_processed",
                                metadata={"rows": outcome["report"]["source_rows"],
                                          "flagged": outcome["report"]["flagged_count"]})
        return Response(outcome)


class FreelanceJarvisPlanView(APIView):
    permission_classes = [IsAuthenticated, FounderFreelancePermission]
    throttle_classes = [FreelanceAIThrottle]
    parser_classes = [JSONParser]

    def post(self, request):
        if request.data.get("consent") is not True:
            return Response({"detail": "Explicit AI processing consent required."}, status=400)
        # Only high-level task descriptions; never upload or forward source documents.
        task = str(request.data.get("task") or "").strip()
        if not task or len(task) > 1200:
            return Response({"detail": "Provide a task description under 1,200 characters."}, status=400)
        if request.data.get("file") or request.data.get("document"):
            return Response({"detail": "Client files are not accepted by Jarvis planning."}, status=400)
        try:
            result = create_sync_response(
                user_id=request.user.id,
                message=task,
                instructions=(
                    "You are Sync Assist's freelance planning assistant. Propose a safe "
                    "step-by-step plan for CSV/data cleanup and quality assurance. "
                    "Never claim you ran tools, contacted clients, inspected files, "
                    "submitted proposals or delivered anything. Never solicit secrets. "
                    "Ask for human review of uncertain matches and client authorization "
                    "before any use of third-party processing. Plain text, concise."
                ),
                metadata={"feature": "freelance_planning", "user": str(request.user.pk)},
                timeout_seconds=25, max_output_tokens=600,
            )
        except SyncAIConfigurationError:
            return Response({"detail": "Sync Assist AI is not configured."}, status=503)
        except SyncAIProviderError:
            return Response({"detail": "Sync Assist could not prepare the plan."}, status=502)
        AuditLog.objects.create(actor=request.user, action="freelance.pilot.jarvis_plan",
                                metadata={"tokens": result.total_tokens, "model": result.model})
        return Response({"plan": result.text, "model": result.model,
                         "note": "Planning only; no files processed or external actions performed."})
