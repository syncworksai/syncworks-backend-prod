from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
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
    out = []
    seen = set()
    for raw in value[:limit]:
        text = str(raw or "").strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text[:120])
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
        data={
            "category": "SCHEDULE",
            "appointment_id": appointment.id,
            "business_id": appointment.business_id,
            "route": "/customer/appointments",
            "push_ready": True,
        },
    )
    return _safe_email(title, f"{body}\n\nOpen SyncWorks to respond to this appointment.", appointment.customer.email)


def _notify_business(appointment, title, body):
    Notification.objects.create(
        recipient=appointment.business.owner,
        actor=appointment.customer,
        type=Notification.TYPE_REMINDER,
        title=title,
        body=body,
        data={
            "category": "SCHEDULE",
            "appointment_id": appointment.id,
            "customer_id": appointment.customer_id,
            "route": "/sbo/appointments",
            "push_ready": True,
        },
    )
    recipient = appointment.business.business_email or appointment.business.owner.email
    return _safe_email(title, f"{body}\n\nOpen SyncWorks Business to review the scheduling update.", recipient)


class ProfessionalPracticeSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            business, member = _active_business(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=404)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        profile, _ = ProfessionalPracticeProfile.objects.get_or_create(business=business)
        return Response(_practice_payload(profile))

    def patch(self, request):
        try:
            business, member = _active_business(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=404)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        if not _can_manage_schedule(request, business, member):
            return Response({"detail": "Schedule/settings permission required."}, status=403)

        profile, _ = ProfessionalPracticeProfile.objects.get_or_create(business=business)
        allowed_types = {choice for choice, _ in ProfessionalPracticeProfile.PracticeType.choices}
        practice_type = str(request.data.get("practice_type") or profile.practice_type).upper()
        if practice_type not in allowed_types:
            return Response({"detail": "Invalid practice type."}, status=400)
        profile.practice_type = practice_type
        if "scheduling_enabled" in request.data:
            profile.scheduling_enabled = bool(request.data.get("scheduling_enabled"))
        if "accepting_new_patients" in request.data:
            profile.accepting_new_patients = bool(request.data.get("accepting_new_patients"))
        if "accepted_insurance" in request.data:
            profile.accepted_insurance = _normalize_strings(request.data.get("accepted_insurance"))
        if "appointment_types" in request.data:
            profile.appointment_types = _clean_appointment_types(request.data.get("appointment_types"))
        if "weekly_schedule" in request.data and isinstance(request.data.get("weekly_schedule"), dict):
            profile.weekly_schedule = request.data.get("weekly_schedule")
        for field in ("booking_lead_minutes", "booking_buffer_minutes"):
            if field in request.data:
                try:
                    setattr(profile, field, max(0, min(int(request.data.get(field) or 0), 10080)))
                except (TypeError, ValueError):
                    pass
        profile.save()
        return Response(_practice_payload(profile))


class ProfessionalDiscoveryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        practice_type = str(request.query_params.get("practice_type") or "").strip().upper()
        insurance = str(request.query_params.get("insurance") or "").strip().lower()
        city = str(request.query_params.get("city") or "").strip()
        state_value = str(request.query_params.get("state") or "").strip().upper()
        zip_value = str(request.query_params.get("zip") or "").strip()
        qs = ProfessionalPracticeProfile.objects.select_related("business").filter(
            scheduling_enabled=True,
            business__is_active=True,
        )
        if practice_type:
            qs = qs.filter(practice_type=practice_type)
        if city:
            qs = qs.filter(business__city__iexact=city)
        if state_value:
            qs = qs.filter(business__state__iexact=state_value)
        if zip_value:
            qs = qs.filter(business__base_zip__startswith=zip_value[:5])

        rows = []
        for profile in qs[:100]:
            payload = _practice_payload(profile)
            accepted = [str(x).lower() for x in payload["accepted_insurance"]]
            if insurance and insurance not in accepted:
                continue
            payload["insurance_match"] = bool(insurance and insurance in accepted)
            payload["insurance_self_reported"] = True
            rows.append(payload)
        return Response({"results": rows, "count": len(rows), "insurance_filter": insurance})


class BusinessProfessionalAppointmentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            business, member = _active_business(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=404)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        rows = ProfessionalAppointment.objects.select_related("business", "customer").filter(business=business)[:250]
        return Response({"results": [_appointment_payload(row) for row in rows]})

    def post(self, request):
        try:
            business, member = _active_business(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        except LookupError as exc:
            return Response({"detail": str(exc)}, status=404)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        if not _can_manage_schedule(request, business, member):
            return Response({"detail": "Schedule permission required."}, status=403)

        email = str(request.data.get("customer_email") or "").strip().lower()
        customer = User.objects.filter(email__iexact=email).first() if email else None
        if not customer:
            return Response({"detail": "The patient must have a SyncWorks account using that email before an appointment can be sent."}, status=400)
        start = parse_datetime(str(request.data.get("proposed_start") or ""))
        if not start:
            return Response({"detail": "A valid proposed_start is required."}, status=400)
        if timezone.is_naive(start):
            start = timezone.make_aware(start, timezone.get_current_timezone())
        duration = request.data.get("duration_minutes") or 30
        try:
            duration = max(5, min(int(duration), 480))
        except (TypeError, ValueError):
            duration = 30
        end = start + timedelta(minutes=duration)
        note = str(request.data.get("scheduling_note") or "").strip()[:1000]
        row = ProfessionalAppointment.objects.create(
            business=business,
            customer=customer,
            appointment_type=str(request.data.get("appointment_type") or "Appointment").strip()[:120],
            status=ProfessionalAppointment.Status.PROPOSED,
            proposed_start=start,
            proposed_end=end,
            location=str(request.data.get("location") or business.address or "").strip()[:240],
            insurance_plan=str(request.data.get("insurance_plan") or "").strip()[:120],
            scheduling_note=note,
        )
        when = timezone.localtime(start).strftime("%a %b %-d at %-I:%M %p")
        emailed = _notify_customer(row, "Appointment proposed", f"{business.name} proposed {row.appointment_type} for {when}.")
        payload = _appointment_payload(row)
        payload["email_sent"] = emailed
        payload["push_ready"] = True
        return Response(payload, status=status.HTTP_201_CREATED)


class CustomerProfessionalAppointmentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = ProfessionalAppointment.objects.select_related("business", "customer").filter(customer=request.user)[:250]
        return Response({"results": [_appointment_payload(row) for row in rows]})


class CustomerProfessionalAppointmentResponseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, appointment_id: int):
        row = ProfessionalAppointment.objects.select_related("business", "customer").filter(pk=appointment_id, customer=request.user).first()
        if not row:
            return Response({"detail": "Appointment not found."}, status=404)
        action = str(request.data.get("action") or "").strip().upper()
        mapping = {
            "ACCEPT": ProfessionalAppointment.Status.ACCEPTED,
            "DECLINE": ProfessionalAppointment.Status.DECLINED,
            "RESCHEDULE": ProfessionalAppointment.Status.RESCHEDULE_REQUESTED,
        }
        if action not in mapping:
            return Response({"detail": "action must be ACCEPT, DECLINE, or RESCHEDULE."}, status=400)
        row.mark_response(mapping[action])
        if action == "RESCHEDULE":
            row.reschedule_note = str(request.data.get("reschedule_note") or "").strip()[:1000]
            windows = request.data.get("preferred_windows")
            if isinstance(windows, list):
                row.preferred_windows = windows[:10]
        row.save(update_fields=["status", "responded_at", "reschedule_note", "preferred_windows", "updated_at"])
        title = "Appointment accepted" if action == "ACCEPT" else "Appointment declined" if action == "DECLINE" else "New appointment time requested"
        body = f"{row.customer.get_full_name() or row.customer.email} updated the {row.appointment_type} appointment."
        emailed = _notify_business(row, title, body)
        payload = _appointment_payload(row)
        payload["email_sent"] = emailed
        payload["push_ready"] = True
        return Response(payload)
