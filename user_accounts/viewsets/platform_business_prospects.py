"""Founder-only, auditable acquisition tickets for business onboarding."""
from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import (
    Business, PlatformBusinessProspect, PlatformProspectActivity,
)
from user_accounts.services.god_mode import is_god_mode


class IsFounderGodMode(BasePermission):
    def has_permission(self, request, view):
        return is_god_mode(getattr(request, "user", None))


def _signup_url(prospect):
    base = (getattr(settings, "FRONTEND_URL", "") or "https://syncworksapp.com").rstrip("/")
    return f"{base}/register?{urlencode({'business': '1', 'email': prospect.email})}"


def _reconcile_signup(prospect):
    """Only attribute a verified owner's business when the match is unambiguous."""
    if prospect.linked_business_id or not prospect.email:
        return
    candidates = list(
        Business.objects.filter(owner__email__iexact=prospect.email)
        .order_by("-created_at")[:10]
    )
    if not candidates:
        return
    same_name = [b for b in candidates if b.name.strip().casefold() == prospect.company_name.strip().casefold()]
    match = same_name[0] if len(same_name) == 1 else candidates[0] if len(candidates) == 1 else None
    if match is None:
        return  # Never guess when a contact controls several companies.
    prospect.linked_business = match
    prospect.signed_up_at = match.created_at or timezone.now()
    fields = ["linked_business", "signed_up_at", "updated_at"]
    if prospect.status not in (PlatformBusinessProspect.Status.WON, PlatformBusinessProspect.Status.LOST):
        prospect.status = PlatformBusinessProspect.Status.REGISTERED
        fields.append("status")
    prospect.save(update_fields=fields)


class PlatformProspectActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformProspectActivity
        fields = ["id", "kind", "subject", "body", "recipient", "created_at"]
        read_only_fields = fields


class PlatformBusinessProspectSerializer(serializers.ModelSerializer):
    activities = PlatformProspectActivitySerializer(many=True, read_only=True)
    signed_up = serializers.SerializerMethodField()
    signup_url = serializers.SerializerMethodField()

    class Meta:
        model = PlatformBusinessProspect
        fields = [
            "id", "company_name", "contact_name", "email", "phone", "industry",
            "interests", "notes", "next_action", "follow_up_at", "status",
            "pilot_status", "pilot_checks", "pilot_feedback",
            "last_invited_at", "linked_business", "signed_up", "signed_up_at",
            "signup_url", "activities", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "last_invited_at", "linked_business", "signed_up",
            "signed_up_at", "signup_url", "activities", "created_at", "updated_at",
        ]

    def validate(self, attrs):
        desired = attrs.get("status")
        if desired in (PlatformBusinessProspect.Status.REGISTERED, PlatformBusinessProspect.Status.WON):
            if not (self.instance and self.instance.linked_business_id):
                raise serializers.ValidationError({
                    "status": "This status requires a verified linked Business. Refresh signup matching first."
                })
        return attrs

    def validate_pilot_checks(self, value):
        allowed = {"signup", "business", "settings", "intake", "estimate", "dispatch", "invoice", "payment", "password_reset", "feedback"}
        if not isinstance(value, dict) or set(value) - allowed or any(type(v) is not bool for v in value.values()):
            raise serializers.ValidationError("Provide only supported checklist names with true/false values.")
        return value

    def validate_pilot_feedback(self, value):
        if len(value) > 4000:
            raise serializers.ValidationError("Keep tester feedback under 4,000 characters.")
        return value

    def validate_interests(self, value):
        if not isinstance(value, list) or len(value) > 20 or any(not isinstance(v, str) or len(v) > 80 for v in value):
            raise serializers.ValidationError("Choose up to 20 short feature interests.")
        return list(dict.fromkeys(v.strip() for v in value if v.strip()))

    def get_signed_up(self, obj):
        return bool(obj.linked_business_id)

    def get_signup_url(self, obj):
        return _signup_url(obj)


class PlatformBusinessProspectViewSet(viewsets.ModelViewSet):
    serializer_class = PlatformBusinessProspectSerializer
    permission_classes = [IsAuthenticated, IsFounderGodMode]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return (
            PlatformBusinessProspect.objects.select_related("linked_business")
            .prefetch_related("activities")
            .order_by("-updated_at", "-id")
        )

    def list(self, request, *args, **kwargs):
        # Keep attribution current when a previously invited owner signs up.
        for prospect in self.get_queryset().filter(linked_business__isnull=True, email__gt="")[:500]:
            _reconcile_signup(prospect)
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        _reconcile_signup(self.get_object())
        return super().retrieve(request, *args, **kwargs)

    def perform_create(self, serializer):
        prospect = serializer.save(created_by=self.request.user)
        _reconcile_signup(prospect)
        PlatformProspectActivity.objects.create(
            prospect=prospect, kind=PlatformProspectActivity.Kind.STATUS,
            subject="Prospect created", body=f"Initial status: {prospect.status}",
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        old = self.get_object()
        previous = old.status
        old_pilot = old.pilot_status
        old_checks = dict(old.pilot_checks or {})
        prospect = serializer.save()
        if prospect.pilot_status != old_pilot or (prospect.pilot_checks or {}) != old_checks:
            PlatformProspectActivity.objects.create(
                prospect=prospect, kind=PlatformProspectActivity.Kind.STATUS,
                subject=f"Pilot: {old_pilot} → {prospect.pilot_status}",
                body=f"Checklist {sum(bool(x) for x in (prospect.pilot_checks or {}).values())}/10 manually checked",
                created_by=self.request.user,
            )
        if prospect.status != previous:
            PlatformProspectActivity.objects.create(
                prospect=prospect, kind=PlatformProspectActivity.Kind.STATUS,
                subject=f"{previous} → {prospect.status}",
                created_by=self.request.user,
            )

    @action(detail=False, methods=["get"], url_path="metrics")
    def metrics(self, request):
        for prospect in self.get_queryset().filter(linked_business__isnull=True, email__gt="")[:500]:
            _reconcile_signup(prospect)
        qs = PlatformBusinessProspect.objects.all()
        total = qs.count()
        registered = qs.filter(linked_business__isnull=False).count()
        won = qs.filter(status=PlatformBusinessProspect.Status.WON).count()
        invited = qs.filter(last_invited_at__isnull=False).count()
        contacted = qs.filter(
            Q(status__in=[
                PlatformBusinessProspect.Status.CONTACTED,
                PlatformBusinessProspect.Status.INVITED,
                PlatformBusinessProspect.Status.DEMO,
                PlatformBusinessProspect.Status.REGISTERED,
                PlatformBusinessProspect.Status.WON,
            ]) | Q(last_invited_at__isnull=False)
        ).count()
        invited_registered = qs.filter(last_invited_at__isnull=False, linked_business__isnull=False).count()
        pilot = {code: qs.filter(pilot_status=code).count() for code in PlatformBusinessProspect.PilotStatus.values}
        return Response({
            "pilot": pilot,
            "total": total, "contacted": contacted, "invited": invited,
            "registered": registered, "won": won,
            "lost": qs.filter(status=PlatformBusinessProspect.Status.LOST).count(),
            "followups_due": qs.filter(follow_up_at__lte=timezone.now())
                .exclude(status__in=[PlatformBusinessProspect.Status.WON, PlatformBusinessProspect.Status.LOST]).count(),
            "prospect_to_signup_pct": round(registered * 100 / total, 1) if total else 0,
            "prospect_to_won_pct": round(won * 100 / total, 1) if total else 0,
            "invited_to_signup_pct": round(invited_registered * 100 / invited, 1) if invited else 0,
            "note": "Won is a manually confirmed sales stage. Signed up is verified by matching a registered owner's email; Stripe payment activation is not inferred.",
        })

    @action(detail=True, methods=["post"], url_path="send-invite")
    def send_invite(self, request, pk=None):
        prospect = self.get_object()
        if not prospect.email:
            return Response({"detail": "Add an email address before sending an invitation."}, status=400)
        if prospect.last_invited_at and timezone.now() - prospect.last_invited_at < timedelta(minutes=2):
            return Response({"detail": "Invitation was recently sent. Check the activity log before resending."}, status=429)
        subject = "Your SyncWorks Business invitation"
        body = (
            f"Hi {prospect.contact_name or 'there'},\n\n"
            f"I'd like to invite {prospect.company_name} to try SyncWorks for customer requests, "
            "scheduling, job management and invoicing.\n\n"
            "Create your account and follow the guided Business setup here:\n"
            f"{_signup_url(prospect)}\n\n"
            "Once you create your account, choose Add My Business and complete the guided steps. "
            "We'll help you test the workflow before going live.\n\n"
            "— SyncWorks"
        )
        try:
            count = send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [prospect.email], fail_silently=False)
        except Exception:
            return Response({"detail": "Email could not be handed to the mail provider. No invitation has been recorded as sent."}, status=503)
        if count != 1:
            return Response({"detail": "Email provider did not accept this invitation."}, status=503)
        now = timezone.now()
        prospect.last_invited_at = now
        if prospect.status in [PlatformBusinessProspect.Status.NEW, PlatformBusinessProspect.Status.CONTACTED]:
            prospect.status = PlatformBusinessProspect.Status.INVITED
        prospect.save(update_fields=["last_invited_at", "status", "updated_at"])
        PlatformProspectActivity.objects.create(
            prospect=prospect, kind=PlatformProspectActivity.Kind.INVITATION,
            subject=subject, body=body, recipient=prospect.email,
            created_by=request.user,
        )
        return Response({"detail": "Invitation handed to email provider and logged.", "prospect": self.get_serializer(prospect).data})

    @action(detail=True, methods=["post"], url_path="log-activity")
    def log_activity(self, request, pk=None):
        prospect = self.get_object()
        kind = str(request.data.get("kind") or "NOTE").upper()
        allowed = {
            PlatformProspectActivity.Kind.NOTE,
            PlatformProspectActivity.Kind.CALL,
            PlatformProspectActivity.Kind.EMAIL,
            PlatformProspectActivity.Kind.MEETING,
        }
        if kind not in allowed:
            return Response({"detail": "Invalid manual activity type."}, status=400)
        subject = str(request.data.get("subject") or "").strip()[:200]
        body = str(request.data.get("body") or "").strip()[:4000]
        if not body:
            return Response({"detail": "Add an activity note."}, status=400)
        item = PlatformProspectActivity.objects.create(
            prospect=prospect, kind=kind, subject=subject,
            body=body, created_by=request.user,
        )
        return Response(PlatformProspectActivitySerializer(item).data, status=status.HTTP_201_CREATED)
