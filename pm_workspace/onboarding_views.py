"""PM lead -> reusable applicant profile -> resident workflow.

The application pilot deliberately does not collect SSNs, DOB, ID numbers,
financial account details, screening reports, or electronic signatures. Those
need a permissioned document/intake provider and separate legal review.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import uuid4

from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .lead_models import PMLead
from .leasing_views import requested_workspace
from .models import PMProperty, PMTenant
from .property_profile_models import PMPropertyProfile

SALT = "syncworks-pm-application-link-v1"
MAX_AGE = 7 * 24 * 60 * 60
APPLICATION_FIELDS = {
    "phone": 40, "preferred_contact": 24, "preferred_move_in": 12,
    "housing_notes": 500, "pets_notes": 250, "agent_name": 120,
    "agent_email": 254, "agency_name": 180, "voucher_code_hint": 80,
    "household_notes": 400,
}
HOUSING_FIELDS = {"accepts_section8", "proposed_rent", "voucher_payment_standard",
                  "approved_tenant_share", "approved_hap_share", "approval_status",
                  "verified_through", "housing_authority", "notes"}


def _onboarding(lead):
    return dict((lead.metadata or {}).get("pm_onboarding") or {})


def _safe_money(value):
    if value in (None, ""):
        return ""
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > 9999999:
            return None
        return str(amount.quantize(Decimal("0.01")))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _save_profile(lead, data, workspace, *, applicant=False):
    current = _onboarding(lead)
    for field, limit in APPLICATION_FIELDS.items():
        if field in data:
            current[field] = str(data.get(field) or "").strip()[:limit]
    if current.get("agent_email"):
        try:
            validate_email(current["agent_email"])
        except ValidationError:
            return "Enter a valid housing agent email."
    if "voucher_amount" in data:
        amount = _safe_money(data.get("voucher_amount"))
        if amount is None:
            return "Enter a valid voucher payment standard."
        current["voucher_amount"] = amount
    if "voucher_bedrooms" in data:
        try:
            count = int(data.get("voucher_bedrooms") or 0)
        except (ValueError, TypeError):
            return "Voucher bedrooms must be a whole number."
        if count < 0 or count > 20:
            return "Voucher bedrooms must be between 0 and 20."
        current["voucher_bedrooms"] = count
    if "section8_requested" in data:
        current["section8_requested"] = data["section8_requested"] is True
        lead.lead_type = PMLead.LeadType.SECTION8 if current["section8_requested"] else PMLead.LeadType.REGULAR
    if "property_id" in data:
        prop_id = data.get("property_id")
        if prop_id:
            prop = PMProperty.objects.filter(workspace=workspace, pk=prop_id).first()
            if not prop:
                return "Choose a property in this PM portfolio."
            lead.property = prop
        else:
            lead.property = None
    if "preferred_move_in" in data:
        raw = current.get("preferred_move_in")
        if raw:
            day = parse_date(raw)
            if not day or day.isoformat() != raw:
                return "Enter a valid move-in date."
            lead.requested_start = day
    if "phone" in data:
        lead.phone = current.get("phone", "")
    if "pets_notes" in data:
        lead.pet_notes = current.get("pets_notes", "")
    if "adults" in data or "children" in data or "pets" in data:
        for field in ("adults", "children", "pets"):
            if field not in data:
                continue
            try:
                value = int(data[field])
            except (TypeError, ValueError):
                return field + " must be a whole number."
            if not 0 <= value <= 50:
                return field + " must be between 0 and 50."
            setattr(lead, field, value)
    lead.metadata = {**(lead.metadata or {}), "pm_onboarding": current}
    return None


def _application_payload(lead):
    profile = _onboarding(lead)
    return {
        "lead_id": lead.id, "name": lead.full_name, "email": lead.email,
        "phone": lead.phone, "adults": lead.adults, "children": lead.children,
        "pets": lead.pets, "property_id": lead.property_id,
        "property_name": lead.property.name if lead.property_id else "",
        "section8_requested": lead.lead_type == PMLead.LeadType.SECTION8,
        "application": {key: profile.get(key, lead.phone if key == "phone" else "") for key in APPLICATION_FIELDS},
        "voucher_amount": profile.get("voucher_amount", ""),
        "voucher_bedrooms": profile.get("voucher_bedrooms", 0),
        "application_status": profile.get("application_status", "NOT_STARTED"),
        "submitted_at": profile.get("submitted_at", ""),
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pm_onboarding_overview(request):
    workspace = requested_workspace(request)
    leads = PMLead.objects.filter(workspace=workspace)
    properties = PMProperty.objects.filter(workspace=workspace).order_by("name", "id")
    counts = {row.id: leads.filter(property_id=row.id).count() for row in properties}
    return Response({
        "workspace_id": workspace.id,
        "leads": leads.count(),
        "applications_submitted": sum(_onboarding(lead).get("application_status") == "SUBMITTED" for lead in leads),
        "tenants": PMTenant.objects.filter(workspace=workspace).count(),
        "properties": [{
            "id": prop.id, "name": prop.name, "address": prop.address,
            "state": prop.state, "inquiries": counts[prop.id],
        } for prop in properties],
        "workflow": ["LEAD", "APPLICATION", "APPROVAL", "LEASE", "SIGNATURE", "MOVE_IN", "BILLING"],
    })


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def pm_lead_application_profile(request, lead_id):
    workspace = requested_workspace(request)
    lead = PMLead.objects.select_for_update().select_related("property").filter(workspace=workspace, pk=lead_id).first()
    if lead is None:
        return Response({"detail": "Lead not found."}, status=404)
    if request.method == "PATCH":
        error = _save_profile(lead, request.data, workspace)
        if error:
            return Response({"detail": error}, status=400)
        lead.save()
    return Response(_application_payload(lead))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def pm_application_invite(request, lead_id):
    workspace = requested_workspace(request)
    lead = PMLead.objects.select_for_update().filter(workspace=workspace, pk=lead_id).first()
    if not lead:
        return Response({"detail": "Lead not found."}, status=404)
    if not lead.email:
        return Response({"detail": "Add the applicant's email before generating a link."}, status=400)
    version = uuid4().hex
    profile = _onboarding(lead)
    profile["invite_nonce"] = version
    profile["application_status"] = "INVITED"
    profile["invite_created_at"] = timezone.now().isoformat()
    lead.metadata = {**(lead.metadata or {}), "pm_onboarding": profile}
    lead.stage = PMLead.Stage.APPLICATION
    lead.save(update_fields=["metadata", "stage", "updated_at"])
    token = signing.dumps({
        "workspace": workspace.pk, "lead": lead.pk,
        "email": lead.email.strip().lower(), "nonce": version,
    }, salt=SALT)
    # Copy-only link: no email is sent until the PM's outbound mailbox is connected.
    return Response({
        "application_path": "/pm/apply?token=" + token,
        "expires_in_days": 7,
        "email": lead.email,
        "detail": "Copy the application link to the intended applicant. They must sign in with the matching email.",
    }, status=201)


def _resolve_application(request, token):
    try:
        claim = signing.loads(token, salt=SALT, max_age=MAX_AGE)
    except (signing.SignatureExpired, signing.BadSignature, TypeError, ValueError):
        return None
    lead = PMLead.objects.select_related("property", "workspace").filter(
        pk=claim.get("lead"), workspace_id=claim.get("workspace")
    ).first()
    if not lead or not lead.email:
        return None
    if lead.email.strip().lower() != claim.get("email"):
        return None
    if request.user.email.strip().lower() != lead.email.strip().lower():
        return None
    if _onboarding(lead).get("invite_nonce") != claim.get("nonce"):
        return None
    return lead


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def pm_resident_application(request):
    token = str(request.query_params.get("token") or request.data.get("token") or "")
    lead = _resolve_application(request, token)
    if not lead:
        return Response({"detail": "The application link is expired, replaced, or does not belong to this signed-in email."}, status=403)
    if request.method == "POST":
        if _onboarding(lead).get("application_status") == "SUBMITTED":
            return Response({"detail": "This application has already been submitted. Contact management for changes."}, status=409)
        error = _save_profile(lead, request.data, lead.workspace, applicant=True)
        if error:
            return Response({"detail": error}, status=400)
        profile = _onboarding(lead)
        profile["application_status"] = "SUBMITTED"
        profile["submitted_at"] = timezone.now().isoformat()
        profile["submitted_by_user"] = request.user.pk
        lead.metadata = {**(lead.metadata or {}), "pm_onboarding": profile}
        lead.stage = PMLead.Stage.APPLICATION
        lead.save()
    return Response(_application_payload(lead))


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
@transaction.atomic
def pm_property_housing_profile(request, property_id):
    workspace = requested_workspace(request)
    prop = PMProperty.objects.filter(workspace=workspace, pk=property_id).first()
    if not prop:
        return Response({"detail": "Property not found."}, status=404)
    profile = PMPropertyProfile.objects.select_for_update().filter(property=prop, workspace=workspace).first()
    current = dict((profile.custom_data or {}).get("section8_pricing") or {}) if profile else {}
    if request.method == "PATCH":
        if profile is None:
            profile = PMPropertyProfile(property=prop, workspace=workspace)
        for field in HOUSING_FIELDS:
            if field not in request.data:
                continue
            raw = request.data[field]
            if field in {"proposed_rent", "voucher_payment_standard", "approved_tenant_share", "approved_hap_share"}:
                raw = _safe_money(raw)
                if raw is None:
                    return Response({"detail": "Enter valid non-negative dollar amounts."}, status=400)
            elif field == "accepts_section8":
                raw = raw is True
            else:
                raw = str(raw or "").strip()[:500]
            current[field] = raw
        # Prices here are advisory; they do not mutate lease or ledger entries.
        profile.custom_data = {**(profile.custom_data or {}), "section8_pricing": current}
        profile.updated_by = request.user
        profile.save(update_fields=["custom_data", "updated_by", "updated_at"])
    return Response({"property_id": prop.id, "property_name": prop.name, "section8_pricing": current,
                     "inquiries": PMLead.objects.filter(workspace=workspace, property=prop).count(),
                     "notice": "Voucher payment standard is not an approved HAP share. This profile does not post rent."})
