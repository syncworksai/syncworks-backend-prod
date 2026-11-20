"""Durable technician shift clock, scoped to active business membership."""
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from user_accounts.models import Business, BusinessMember
from .models import TechnicianShift

def _scope(request):
    raw = request.headers.get("X-Business-Id") or request.query_params.get("business_id")
    try:
        business_id = int(raw)
    except (ValueError, TypeError):
        return None
    business = Business.objects.filter(pk=business_id, is_active=True).first()
    if not business:
        return None
    if business.owner_id != request.user.id and not BusinessMember.objects.filter(business=business, user=request.user, is_active=True).exists():
        return None
    return business

def _serialize(shift):
    if not shift:
        return None
    end = shift.clock_out_at or timezone.now()
    return {"id": shift.pk, "clock_in_at": shift.clock_in_at.isoformat(),
            "clock_out_at": shift.clock_out_at.isoformat() if shift.clock_out_at else None,
            "seconds": max(0, int((end-shift.clock_in_at).total_seconds())),
            "active": shift.clock_out_at is None}

class TechnicianShiftView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business = _scope(request)
        if not business:
            return Response({"detail":"Active business membership required."}, status=403)
        shifts = TechnicianShift.objects.filter(business=business, technician=request.user)
        recent = list(shifts[:15])
        return Response({"active": _serialize(next((x for x in recent if x.clock_out_at is None), None)),
                         "recent": [_serialize(x) for x in recent]})

    @transaction.atomic
    def post(self, request):
        business = _scope(request)
        if not business:
            return Response({"detail":"Active business membership required."}, status=403)
        action = str(request.data.get("action") or "").upper()
        if action not in {"CLOCK_IN", "CLOCK_OUT"}:
            return Response({"detail":"Use CLOCK_IN or CLOCK_OUT."}, status=400)
        active = TechnicianShift.objects.select_for_update().filter(
            business=business, technician=request.user, clock_out_at__isnull=True).first()
        if action == "CLOCK_IN":
            if active:
                return Response({"detail":"Already clocked in.", "active":_serialize(active)}, status=409)
            try:
                with transaction.atomic():
                    active = TechnicianShift.objects.create(business=business, technician=request.user)
            except IntegrityError:
                return Response({"detail":"Shift already active. Refresh the clock."}, status=409)
            return Response({"active":_serialize(active)}, status=201)
        if not active:
            return Response({"detail":"No active shift to clock out."}, status=409)
        active.clock_out_at = timezone.now()
        active.save(update_fields=["clock_out_at"])
        return Response({"active":None, "completed":_serialize(active)})
