from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import (
    Business,
    BusinessMember,
    Notification,
    ProfessionalAppointment,
    ProfessionalPracticeProfile,
    ProfessionalProvider,
    ProfessionalResource,
)

User = get_user_model()


def _active_business(request):
    raw = request.headers.get("X-Business-ID") or request.data.get("business_id") or request.query_params.get("business_id")
    try:
        business_id = int(raw)
    except (TypeError, ValueError):
        raise ValueError("Choose an active business first.")
    business = Business.objects.filter(pk=business_id, is_active=True).first()
    if not business:
        raise LookupError("Business not found.")
    member = BusinessMember.objects.filter(business=business, user=request.user, is_active=True).first()
    if business.owner_id != request.user.id and not member:
        raise PermissionError("You do not have access to this business.")
    return business, member


def _can_manage_schedule(request, business, member):
    return business.owner_id == request.user.id or bool(member and (member.can_manage_schedule or member.can_manage_settings))


def _normalize_strings(value, limit=60):
    if not isinstance(value, list):
        return []
    out, seen = [], set()
    for raw in value[:limit]:
        text = str(raw or "").strip()[:120]
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def _clean_appointment_types(value):
    if not isinstance(value, list):
        return []
    rows = []
    for raw in value[:40]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()[:120]
        if not name:
            continue
        try:
            minutes = max(5, min(int(raw.get("duration_minutes") or 30), 480))
        except (TypeError, ValueError):
            minutes = 30
        rows.append({"name": name, "duration_minutes": minutes, "active": raw.get("active") is not False})
    return rows


def _provider_payload(row):
    return {
        "id": row.id,
        "name": row.name,
        "role_label": row.role_label,
        "active": row.active,
        "appointment_types": row.appointment_types or [],
        "weekly_schedule": row.weekly_schedule or {},
    }


def _resource_payload(row):
    return {
        "id": row.id,
        "name": row.name,
        "resource_type": row.resource_type,
        "resource_type_label": row.get_resource_type_display(),
        "active": row.active,
        "appointment_types": row.appointment_types or [],
    }


def _practice_payload(profile):
    business = profile.business
    return {
        "id": profile.id,
        "business_id": business.id,
        "business_name": business.name,
        "business_email": business.business_email,
        "phone": business.phone,
        "address": business.address,
        "city": business.city,
        "state": business.state,
        "base_zip": business.base_zip,
        "practice_type": profile.practice_type,
        "practice_type_label": profile.get_practice_type_display(),
        "scheduling_enabled": profile.scheduling_enabled,
        "accepting_new_patients": profile.accepting_new_patients,
        "accepted_insurance": profile.accepted_insurance or [],
        "appointment_types": profile.appointment_types or [],
        "weekly_schedule": profile.weekly_schedule or {},
        "booking_lead_minutes": profile.booking_lead_minutes,
        "booking_buffer_minutes": profile.booking_buffer_minutes,
        "scheduling_disclaimer": profile.scheduling_disclaimer,
        "providers": [_provider_payload(row) for row in profile.providers.all()],
        "resources": [_resource_payload(row) for row in profile.resources.all()],
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def _appointment_payload(row):
    business = row.business
    customer = row.customer
    return {
        "id": row.id,
        "business_id": business.id,
        "business_name": business.name,
        "business_phone": business.phone,
        "business_email": business.business_email,
        "customer_id": customer.id,
        "customer_name": (customer.get_full_name() or customer.email or "SyncWorks user").strip(),
        "customer_email": customer.email,
        "provider_id": row.provider_id,
        "provider_name": row.provider.name if row.provider else "",
        "resource_id": row.resource_id,
        "resource_name": row.resource.name if row.resource else "",
        "appointment_type": row.appointment_type,
        "status": row.status,
        "proposed_start": row.proposed_start.isoformat() if row.proposed_start else None,
        "proposed_end": row.proposed_end.isoformat() if row.proposed_end else None,
        "preferred_windows": row.preferred_windows or [],
        "location": row.location,
        "insurance_plan": row.insurance_plan,
        "scheduling_note": row.scheduling_note,
        "reschedule_note": row.reschedule_note,
        "responded_at": row.responded_at.isoformat() if row.responded_at else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _safe_email(subject, body, recipient):
    if not recipient:
        return False
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient], fail_silently=True)
        return True
    except Exception:
        return False


def _notify_customer(appointment, title, body):
    Notification.objects.create(
        recipient=appointment.customer,
        actor=appointment.business.owner,
        type=Notification.TYPE_REMINDER,
        title=title,
        body=body,
        data={"category": "SCHEDULE", "appointment_id": appointment.id, "business_id": appointment.business_id, "route": "/customer/appointments", "push_ready": True},
    )
    return _safe_email(title, f"{body}\n\nOpen SyncWorks to respond to this appointment.", appointment.customer.email)


def _notify_business(appointment, title, body):
    Notification.objects.create(
        recipient=appointment.business.owner,
        actor=appointment.customer,
        type=Notification.TYPE_REMINDER,
        title=title,
        body=body,
        data={"category": "SCHEDULE", "appointment_id": appointment.id, "customer_id": appointment.customer_id, "route": "/sbo/appointments", "push_ready": True},
    )
    recipient = appointment.business.business_email or appointment.business.owner.email
    return _safe_email(title, f"{body}\n\nOpen SyncWorks Business to review the scheduling update.", recipient)


def _time_on(day, raw, fallback):
    try:
        hour, minute = [int(x) for x in str(raw).split(":")[:2]]
        return timezone.make_aware(datetime(day.year, day.month, day.day, hour, minute), timezone.get_current_timezone())
    except Exception:
        return timezone.make_aware(datetime(day.year, day.month, day.day, fallback, 0), timezone.get_current_timezone())


def _slot_conflict(business, start, end, provider_id=None, resource_id=None):
    qs = ProfessionalAppointment.objects.filter(
        business=business,
        status__in=[ProfessionalAppointment.Status.PROPOSED, ProfessionalAppointment.Status.ACCEPTED],
        proposed_start__lt=end,
        proposed_end__gt=start,
    )
    if provider_id and qs.filter(provider_id=provider_id).exists():
        return True
    if resource_id and qs.filter(resource_id=resource_id).exists():
        return True
    if not provider_id and not resource_id and qs.exists():
        return True
    return False


class ProfessionalPracticeSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            business, _ = _active_business(request)
        except ValueError as exc: return Response({"detail": str(exc)}, status=400)
        except LookupError as exc: return Response({"detail": str(exc)}, status=404)
        except PermissionError as exc: return Response({"detail": str(exc)}, status=403)
        profile, _ = ProfessionalPracticeProfile.objects.get_or_create(business=business)
        profile = ProfessionalPracticeProfile.objects.prefetch_related("providers", "resources").get(pk=profile.pk)
        return Response(_practice_payload(profile))

    def patch(self, request):
        try:
            business, member = _active_business(request)
        except ValueError as exc: return Response({"detail": str(exc)}, status=400)
        except LookupError as exc: return Response({"detail": str(exc)}, status=404)
        except PermissionError as exc: return Response({"detail": str(exc)}, status=403)
        if not _can_manage_schedule(request, business, member):
            return Response({"detail": "Schedule/settings permission required."}, status=403)
        profile, _ = ProfessionalPracticeProfile.objects.get_or_create(business=business)
        allowed_types = {choice for choice, _ in ProfessionalPracticeProfile.PracticeType.choices}
        practice_type = str(request.data.get("practice_type") or profile.practice_type).upper()
        if practice_type not in allowed_types:
            return Response({"detail": "Invalid practice type."}, status=400)
        profile.practice_type = practice_type
        if "scheduling_enabled" in request.data: profile.scheduling_enabled = bool(request.data.get("scheduling_enabled"))
        if "accepting_new_patients" in request.data: profile.accepting_new_patients = bool(request.data.get("accepting_new_patients"))
        if "accepted_insurance" in request.data: profile.accepted_insurance = _normalize_strings(request.data.get("accepted_insurance"))
        if "appointment_types" in request.data: profile.appointment_types = _clean_appointment_types(request.data.get("appointment_types"))
        if "weekly_schedule" in request.data and isinstance(request.data.get("weekly_schedule"), dict): profile.weekly_schedule = request.data.get("weekly_schedule")
        for field in ("booking_lead_minutes", "booking_buffer_minutes"):
            if field in request.data:
                try: setattr(profile, field, max(0, min(int(request.data.get(field) or 0), 10080)))
                except (TypeError, ValueError): pass
        profile.save()
        return Response(_practice_payload(ProfessionalPracticeProfile.objects.prefetch_related("providers", "resources").get(pk=profile.pk)))


class ProfessionalProvidersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try: business, _ = _active_business(request)
        except Exception as exc: return Response({"detail": str(exc)}, status=400)
        profile, _ = ProfessionalPracticeProfile.objects.get_or_create(business=business)
        return Response({"results": [_provider_payload(row) for row in profile.providers.all()]})

    def post(self, request):
        try: business, member = _active_business(request)
        except Exception as exc: return Response({"detail": str(exc)}, status=400)
        if not _can_manage_schedule(request, business, member): return Response({"detail": "Schedule/settings permission required."}, status=403)
        name = str(request.data.get("name") or "").strip()[:160]
        if not name: return Response({"detail": "Provider name is required."}, status=400)
        profile, _ = ProfessionalPracticeProfile.objects.get_or_create(business=business)
        row = ProfessionalProvider.objects.create(
            practice=profile,
            name=name,
            role_label=str(request.data.get("role_label") or "").strip()[:120],
            active=request.data.get("active") is not False,
            appointment_types=_normalize_strings(request.data.get("appointment_types")),
            weekly_schedule=request.data.get("weekly_schedule") if isinstance(request.data.get("weekly_schedule"), dict) else {},
        )
        return Response(_provider_payload(row), status=201)


class ProfessionalProviderDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, provider_id):
        try: business, member = _active_business(request)
        except Exception as exc: return Response({"detail": str(exc)}, status=400)
        if not _can_manage_schedule(request, business, member): return Response({"detail": "Schedule/settings permission required."}, status=403)
        row = ProfessionalProvider.objects.filter(pk=provider_id, practice__business=business).first()
        if not row: return Response({"detail": "Provider not found."}, status=404)
        for field in ("name", "role_label"):
            if field in request.data: setattr(row, field, str(request.data.get(field) or "").strip()[:160 if field == "name" else 120])
        if "active" in request.data: row.active = bool(request.data.get("active"))
        if "appointment_types" in request.data: row.appointment_types = _normalize_strings(request.data.get("appointment_types"))
        if "weekly_schedule" in request.data and isinstance(request.data.get("weekly_schedule"), dict): row.weekly_schedule = request.data.get("weekly_schedule")
        row.save()
        return Response(_provider_payload(row))

    def delete(self, request, provider_id):
        try: business, member = _active_business(request)
        except Exception as exc: return Response({"detail": str(exc)}, status=400)
        if not _can_manage_schedule(request, business, member): return Response({"detail": "Schedule/settings permission required."}, status=403)
        ProfessionalProvider.objects.filter(pk=provider_id, practice__business=business).delete()
        return Response(status=204)


class ProfessionalResourcesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try: business, _ = _active_business(request)
        except Exception as exc: return Response({"detail": str(exc)}, status=400)
        profile, _ = ProfessionalPracticeProfile.objects.get_or_create(business=business)
        return Response({"results": [_resource_payload(row) for row in profile.resources.all()]})

    def post(self, request):
        try: business, member = _active_business(request)
        except Exception as exc: return Response({"detail": str(exc)}, status=400)
        if not _can_manage_schedule(request, business, member): return Response({"detail": "Schedule/settings permission required."}, status=403)
        name = str(request.data.get("name") or "").strip()[:160]
        if not name: return Response({"detail": "Resource name is required."}, status=400)
        profile, _ = ProfessionalPracticeProfile.objects.get_or_create(business=business)
        kind = str(request.data.get("resource_type") or ProfessionalResource.ResourceType.ROOM).upper()
        if kind not in {choice for choice, _ in ProfessionalResource.ResourceType.choices}: kind = ProfessionalResource.ResourceType.OTHER
        row = ProfessionalResource.objects.create(practice=profile, name=name, resource_type=kind, active=request.data.get("active") is not False, appointment_types=_normalize_strings(request.data.get("appointment_types")))
        return Response(_resource_payload(row), status=201)


class ProfessionalResourceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, resource_id):
        try: business, member = _active_business(request)
        except Exception as exc: return Response({"detail": str(exc)}, status=400)
        if not _can_manage_schedule(request, business, member): return Response({"detail": "Schedule/settings permission required."}, status=403)
        row = ProfessionalResource.objects.filter(pk=resource_id, practice__business=business).first()
        if not row: return Response({"detail": "Resource not found."}, status=404)
        if "name" in request.data: row.name = str(request.data.get("name") or "").strip()[:160]
        if "resource_type" in request.data:
            kind = str(request.data.get("resource_type") or "OTHER").upper()
            if kind in {choice for choice, _ in ProfessionalResource.ResourceType.choices}: row.resource_type = kind
        if "active" in request.data: row.active = bool(request.data.get("active"))
        if "appointment_types" in request.data: row.appointment_types = _normalize_strings(request.data.get("appointment_types"))
        row.save()
        return Response(_resource_payload(row))

    def delete(self, request, resource_id):
        try: business, member = _active_business(request)
        except Exception as exc: return Response({"detail": str(exc)}, status=400)
        if not _can_manage_schedule(request, business, member): return Response({"detail": "Schedule/settings permission required."}, status=403)
        ProfessionalResource.objects.filter(pk=resource_id, practice__business=business).delete()
        return Response(status=204)


class ProfessionalAvailabilityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try: business, _ = _active_business(request)
        except Exception as exc: return Response({"detail": str(exc)}, status=400)
        profile, _ = ProfessionalPracticeProfile.objects.get_or_create(business=business)
        start_day = parse_date(str(request.query_params.get("date") or "")) or timezone.localdate()
        provider_id = request.query_params.get("provider_id") or None
        resource_id = request.query_params.get("resource_id") or None
        appointment_type = str(request.query_params.get("appointment_type") or "").strip()
        try: duration = max(5, min(int(request.query_params.get("duration_minutes") or 30), 480))
        except (TypeError, ValueError): duration = 30
        provider = ProfessionalProvider.objects.filter(pk=provider_id, practice=profile, active=True).first() if provider_id else None
        resource = ProfessionalResource.objects.filter(pk=resource_id, practice=profile, active=True).first() if resource_id else None
        schedule = provider.weekly_schedule if provider and provider.weekly_schedule else profile.weekly_schedule
        now = timezone.now() + timedelta(minutes=profile.booking_lead_minutes)
        slots = []
        for offset in range(14):
            day = start_day + timedelta(days=offset)
            row = (schedule or {}).get(day.strftime("%A").lower(), {})
            if not row or row.get("open") is False:
                continue
            start = _time_on(day, row.get("start"), 8)
            close = _time_on(day, row.get("end"), 17)
            cursor = start
            while cursor + timedelta(minutes=duration) <= close:
                end = cursor + timedelta(minutes=duration)
                if cursor >= now and not _slot_conflict(business, cursor, end, provider.id if provider else None, resource.id if resource else None):
                    slots.append({"start": cursor.isoformat(), "end": end.isoformat(), "provider_id": provider.id if provider else None, "provider_name": provider.name if provider else "", "resource_id": resource.id if resource else None, "resource_name": resource.name if resource else "", "appointment_type": appointment_type})
                cursor += timedelta(minutes=max(15, duration + profile.booking_buffer_minutes))
                if len(slots) >= 80:
                    break
            if len(slots) >= 80:
                break
        return Response({"results": slots, "count": len(slots)})


class ProfessionalDiscoveryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        practice_type = str(request.query_params.get("practice_type") or "").strip().upper()
        insurance = str(request.query_params.get("insurance") or "").strip().lower()
        city = str(request.query_params.get("city") or "").strip()
        state_value = str(request.query_params.get("state") or "").strip().upper()
        zip_value = str(request.query_params.get("zip") or "").strip()
        qs = ProfessionalPracticeProfile.objects.select_related("business").prefetch_related("providers", "resources").filter(scheduling_enabled=True, business__is_active=True)
        if practice_type: qs = qs.filter(practice_type=practice_type)
        if city: qs = qs.filter(business__city__iexact=city)
        if state_value: qs = qs.filter(business__state__iexact=state_value)
        if zip_value: qs = qs.filter(business__base_zip__startswith=zip_value[:5])
        rows = []
        for profile in qs[:100]:
            payload = _practice_payload(profile)
            accepted = [str(x).lower() for x in payload["accepted_insurance"]]
            if insurance and insurance not in accepted: continue
            payload["insurance_match"] = bool(insurance and insurance in accepted)
            payload["insurance_self_reported"] = True
            rows.append(payload)
        return Response({"results": rows, "count": len(rows), "insurance_filter": insurance})


class BusinessProfessionalAppointmentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try: business, _ = _active_business(request)
        except Exception as exc: return Response({"detail": str(exc)}, status=400)
        rows = ProfessionalAppointment.objects.select_related("business", "customer", "provider", "resource").filter(business=business)[:250]
        return Response({"results": [_appointment_payload(row) for row in rows]})

    def post(self, request):
        try: business, member = _active_business(request)
        except Exception as exc: return Response({"detail": str(exc)}, status=400)
        if not _can_manage_schedule(request, business, member): return Response({"detail": "Schedule permission required."}, status=403)
        email = str(request.data.get("customer_email") or "").strip().lower()
        customer = User.objects.filter(email__iexact=email).first() if email else None
        if not customer: return Response({"detail": "The patient must have a SyncWorks account using that email before an appointment can be sent."}, status=400)
        start = parse_datetime(str(request.data.get("proposed_start") or ""))
        if not start: return Response({"detail": "A valid proposed_start is required."}, status=400)
        if timezone.is_naive(start): start = timezone.make_aware(start, timezone.get_current_timezone())
        try: duration = max(5, min(int(request.data.get("duration_minutes") or 30), 480))
        except (TypeError, ValueError): duration = 30
        end = start + timedelta(minutes=duration)
        profile, _ = ProfessionalPracticeProfile.objects.get_or_create(business=business)
        provider = ProfessionalProvider.objects.filter(pk=request.data.get("provider_id"), practice=profile, active=True).first() if request.data.get("provider_id") else None
        resource = ProfessionalResource.objects.filter(pk=request.data.get("resource_id"), practice=profile, active=True).first() if request.data.get("resource_id") else None
        if _slot_conflict(business, start, end, provider.id if provider else None, resource.id if resource else None):
            return Response({"detail": "That provider or room/resource is already booked during the selected time."}, status=409)
        row = ProfessionalAppointment.objects.create(
            business=business,
            customer=customer,
            provider=provider,
            resource=resource,
            appointment_type=str(request.data.get("appointment_type") or "Appointment").strip()[:120],
            status=ProfessionalAppointment.Status.PROPOSED,
            proposed_start=start,
            proposed_end=end,
            location=str(request.data.get("location") or business.address or "").strip()[:240],
            insurance_plan=str(request.data.get("insurance_plan") or "").strip()[:120],
            scheduling_note=str(request.data.get("scheduling_note") or "").strip()[:1000],
        )
        when = timezone.localtime(start).strftime("%a %b %d at %I:%M %p").replace(" 0", " ")
        detail = f" with {provider.name}" if provider else ""
        emailed = _notify_customer(row, "Appointment proposed", f"{business.name} proposed {row.appointment_type}{detail} for {when}.")
        payload = _appointment_payload(row)
        payload["email_sent"] = emailed
        payload["push_ready"] = True
        return Response(payload, status=status.HTTP_201_CREATED)


class CustomerProfessionalAppointmentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = ProfessionalAppointment.objects.select_related("business", "customer", "provider", "resource").filter(customer=request.user)[:250]
        return Response({"results": [_appointment_payload(row) for row in rows]})


class CustomerProfessionalAppointmentResponseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, appointment_id: int):
        row = ProfessionalAppointment.objects.select_related("business", "customer", "provider", "resource").filter(pk=appointment_id, customer=request.user).first()
        if not row: return Response({"detail": "Appointment not found."}, status=404)
        action = str(request.data.get("action") or "").strip().upper()
        mapping = {"ACCEPT": ProfessionalAppointment.Status.ACCEPTED, "DECLINE": ProfessionalAppointment.Status.DECLINED, "RESCHEDULE": ProfessionalAppointment.Status.RESCHEDULE_REQUESTED}
        if action not in mapping: return Response({"detail": "action must be ACCEPT, DECLINE, or RESCHEDULE."}, status=400)
        row.mark_response(mapping[action])
        if action == "RESCHEDULE":
            row.reschedule_note = str(request.data.get("reschedule_note") or "").strip()[:1000]
            windows = request.data.get("preferred_windows")
            if isinstance(windows, list): row.preferred_windows = windows[:10]
        row.save(update_fields=["status", "responded_at", "reschedule_note", "preferred_windows", "updated_at"])
        title = "Appointment accepted" if action == "ACCEPT" else "Appointment declined" if action == "DECLINE" else "New appointment time requested"
        body = f"{row.customer.get_full_name() or row.customer.email} updated the {row.appointment_type} appointment."
        emailed = _notify_business(row, title, body)
        payload = _appointment_payload(row)
        payload["email_sent"] = emailed
        payload["push_ready"] = True
        return Response(payload)
