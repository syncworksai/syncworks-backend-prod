from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import PMProject, PMProjectUpdate, PMProperty, PMTenant, PMTenantInvitation, PMWorkspace
from .serializers import (
    PMProjectSerializer,
    PMProjectUpdateSerializer,
    PMPropertySerializer,
    PMTenantInvitationSerializer,
    PMTenantSerializer,
    PMWorkspaceSerializer,
)


def _workspace_for_user(user, workspace_id=None):
    qs = PMWorkspace.objects.filter(owner=user, is_active=True)
    if workspace_id:
        return qs.filter(pk=workspace_id).first()
    return qs.order_by("id").first()


def _requested_workspace(request):
    workspace_id = (
        request.headers.get("X-PM-Workspace-ID")
        or request.query_params.get("workspace_id")
        or (request.data.get("workspace_id") if isinstance(request.data, dict) else None)
    )
    workspace = _workspace_for_user(request.user, workspace_id)
    if not workspace:
        raise PermissionDenied("Create or select a Property Management portfolio first.")
    return workspace


def _user_defaults(user):
    full_name = str(getattr(user, "get_full_name", lambda: "")() or "").strip()
    if not full_name:
        full_name = " ".join(filter(None, [getattr(user, "first_name", ""), getattr(user, "last_name", "")])).strip()
    email = str(getattr(user, "email", "") or "").strip()
    phone = str(getattr(user, "phone", "") or getattr(user, "phone_number", "") or "").strip()
    return {
        "manager_name": full_name,
        "sender_name": full_name,
        "office_email": email,
        "tenant_email": email,
        "reply_to_email": email,
        "phone": phone,
    }


class PMWorkspaceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMWorkspaceSerializer

    def get_queryset(self):
        return PMWorkspace.objects.filter(owner=self.request.user).order_by("name", "id")

    def perform_create(self, serializer):
        existing = PMWorkspace.objects.filter(owner=self.request.user, is_active=True).count()
        if existing >= 1 and not (self.request.user.is_staff or self.request.user.is_superuser):
            raise ValidationError({
                "detail": "Your first portfolio is free. Additional portfolios require the $9.99 monthly plan.",
                "code": "PM_ADDITIONAL_PORTFOLIO_PAYMENT_REQUIRED",
                "monthly_price": "9.99",
            })
        serializer.save(owner=self.request.user)

    @action(detail=False, methods=["get"], url_path="defaults")
    def defaults(self, request):
        return Response({
            **_user_defaults(request.user),
            "portfolio_count": PMWorkspace.objects.filter(owner=request.user, is_active=True).count(),
            "free_portfolios": 1,
            "additional_portfolio_price": "9.99",
        })

    @action(detail=False, methods=["get", "patch"], url_path="current")
    def current(self, request):
        workspace_id = request.headers.get("X-PM-Workspace-ID") or request.query_params.get("workspace_id")
        workspace = _workspace_for_user(request.user, workspace_id)
        if request.method == "GET":
            if not workspace:
                return Response({"detail": "No PM workspace exists yet.", "defaults": _user_defaults(request.user)}, status=status.HTTP_404_NOT_FOUND)
            return Response(self.get_serializer(workspace).data)

        if workspace:
            serializer = self.get_serializer(workspace, data=request.data, partial=True)
        else:
            if PMWorkspace.objects.filter(owner=request.user, is_active=True).exists() and not (request.user.is_staff or request.user.is_superuser):
                return Response({
                    "detail": "Your first portfolio is free. Additional portfolios require the $9.99 monthly plan.",
                    "code": "PM_ADDITIONAL_PORTFOLIO_PAYMENT_REQUIRED",
                    "monthly_price": "9.99",
                }, status=status.HTTP_402_PAYMENT_REQUIRED)
            serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(owner=request.user)
        return Response(serializer.data, status=status.HTTP_200_OK if workspace else status.HTTP_201_CREATED)


class PMPropertyViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMPropertySerializer

    def get_queryset(self):
        workspace = _requested_workspace(self.request)
        return PMProperty.objects.filter(workspace=workspace).order_by("name", "id")

    def perform_create(self, serializer):
        serializer.save(workspace=_requested_workspace(self.request), created_by=self.request.user)


class PMProjectViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMProjectSerializer

    def get_queryset(self):
        workspace = _requested_workspace(self.request)
        qs = PMProject.objects.filter(workspace=workspace).select_related("property", "created_by").prefetch_related("updates__created_by")
        archived = str(self.request.query_params.get("archived", "false")).lower() == "true"
        qs = qs.filter(status=PMProject.Status.ARCHIVED) if archived else qs.exclude(status=PMProject.Status.ARCHIVED)
        search = str(self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(Q(title__icontains=search) | Q(description__icontains=search) | Q(vendor_title__icontains=search) | Q(property__name__icontains=search))
        status_filter = str(self.request.query_params.get("status") or "").strip().upper()
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs.order_by("-updated_at", "-id")

    def perform_create(self, serializer):
        workspace = _requested_workspace(self.request)
        project = serializer.save(workspace=workspace, created_by=self.request.user)
        PMProjectUpdate.objects.create(
            project=project,
            note="Project created.",
            status=project.status,
            progress_percent=project.progress_percent,
            next_action=project.next_action,
            next_action_due=project.next_action_due,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        project = serializer.save()
        if project.status == PMProject.Status.COMPLETED and not project.completed_at:
            project.completed_at = timezone.now()
            project.progress_percent = 100
            project.save(update_fields=["completed_at", "progress_percent", "updated_at"])
        elif project.status != PMProject.Status.COMPLETED and project.completed_at:
            project.completed_at = None
            project.save(update_fields=["completed_at", "updated_at"])

    @action(detail=False, methods=["get"], url_path="metrics")
    def metrics(self, request):
        workspace = _requested_workspace(request)
        qs = PMProject.objects.filter(workspace=workspace).exclude(status=PMProject.Status.ARCHIVED)
        today = timezone.localdate()
        active = qs.exclude(status=PMProject.Status.COMPLETED)
        budget = qs.aggregate(total=Sum("budget_amount"))["total"] or 0
        actual = qs.aggregate(total=Sum("actual_amount"))["total"] or 0
        return Response({
            "total": qs.count(),
            "active": active.count(),
            "overdue": active.filter(target_date__lt=today).count(),
            "blocked": active.exclude(blocker="").count(),
            "awaiting_approval": active.filter(status=PMProject.Status.APPROVAL).count(),
            "due_soon": active.filter(target_date__gte=today, target_date__lte=today + timedelta(days=14)).count(),
            "completed": qs.filter(status=PMProject.Status.COMPLETED).count(),
            "budget_total": str(budget),
            "actual_total": str(actual),
        })

    @action(detail=True, methods=["post"], url_path="add-update")
    @transaction.atomic
    def add_update(self, request, pk=None):
        project = self.get_object()
        serializer = PMProjectUpdateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        update = serializer.save(project=project, created_by=request.user)
        changed = []
        for field in ("status", "progress_percent", "blocker", "next_action", "next_action_due"):
            value = getattr(update, field)
            if value not in (None, ""):
                setattr(project, field, value)
                changed.append(field)
        if project.status == PMProject.Status.COMPLETED:
            project.progress_percent = 100
            project.completed_at = project.completed_at or timezone.now()
            changed.extend(["progress_percent", "completed_at"])
        if changed:
            project.save(update_fields=list(dict.fromkeys(changed + ["updated_at"])))
        return Response(PMProjectUpdateSerializer(update).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request, pk=None):
        project = self.get_object()
        project.status = PMProject.Status.ARCHIVED
        project.archived_at = timezone.now()
        project.save(update_fields=["status", "archived_at", "updated_at"])
        PMProjectUpdate.objects.create(project=project, note="Project archived.", status=project.status, progress_percent=project.progress_percent, created_by=request.user)
        return Response(self.get_serializer(project).data)

    @action(detail=True, methods=["post"], url_path="email-status")
    def email_status(self, request, pk=None):
        project = self.get_object()
        workspace = project.workspace
        raw = request.data.get("emails") or project.update_recipient_emails or ""
        if isinstance(raw, list):
            recipients = [str(item).strip() for item in raw if str(item).strip()]
        else:
            recipients = [item.strip() for item in str(raw).replace(";", ",").split(",") if item.strip()]
        if not recipients:
            return Response({"detail": "Add at least one status update email recipient."}, status=status.HTTP_400_BAD_REQUEST)
        latest = project.updates.order_by("-created_at").first()
        subject = f"{workspace.name}: {project.title} status update"
        body = (
            f"Project: {project.title}\n"
            f"Portfolio: {workspace.name}\n"
            f"Property: {project.property.name if project.property else 'Portfolio-wide'}\n"
            f"Status: {project.get_status_display()}\n"
            f"Progress: {project.progress_percent}%\n"
            f"Target date: {project.target_date or 'Not set'}\n"
            f"Next action: {project.next_action or 'Not set'}\n"
            f"Blocker: {project.blocker or 'None'}\n\n"
            f"Latest update: {latest.note if latest else 'No update note yet.'}\n"
        )
        email = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "notifications@syncworksapp.com"),
            to=recipients,
            reply_to=[workspace.reply_to_email or workspace.office_email] if (workspace.reply_to_email or workspace.office_email) else None,
        )
        try:
            email.send(fail_silently=False)
        except Exception:
            return Response({"detail": "Status email could not be delivered. Check email configuration."}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"detail": "Project status email sent.", "recipients": recipients})


class PMTenantViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMTenantSerializer

    def _workspace(self):
        return _requested_workspace(self.request)

    def get_queryset(self):
        workspace = self._workspace()
        return PMTenant.objects.filter(workspace=workspace).select_related("user").prefetch_related("invitations")

    def perform_create(self, serializer):
        serializer.save(workspace=self._workspace(), created_by=self.request.user)

    def update(self, request, *args, **kwargs):
        tenant = self.get_object()
        old_email = tenant.email.lower()
        response = super().update(request, *args, **kwargs)
        tenant.refresh_from_db()
        if tenant.email.lower() != old_email:
            tenant.invitations.filter(status=PMTenantInvitation.Status.PENDING).update(status=PMTenantInvitation.Status.REVOKED, revoked_at=timezone.now())
            tenant.status = PMTenant.Status.DRAFT
            tenant.save(update_fields=["status", "updated_at"])
            response.data["email_changed"] = True
            response.data["detail"] = "Email updated. Previous invitations were revoked; send a new invitation."
        return response

    @action(detail=True, methods=["post"], url_path="send-invite")
    def send_invite(self, request, pk=None):
        tenant = self.get_object()
        workspace = tenant.workspace
        mode = str(request.data.get("mode") or PMTenantInvitation.Mode.COMPLETE_RECORD).upper()
        if mode not in PMTenantInvitation.Mode.values:
            return Response({"detail": "Invalid invitation mode."}, status=status.HTTP_400_BAD_REQUEST)
        if not tenant.email:
            return Response({"detail": "Tenant email is required."}, status=status.HTTP_400_BAD_REQUEST)
        tenant.invitations.filter(status=PMTenantInvitation.Status.PENDING).update(status=PMTenantInvitation.Status.REVOKED, revoked_at=timezone.now())
        invite = PMTenantInvitation.objects.create(
            tenant=tenant,
            mode=mode,
            sent_to_email=tenant.email,
            sent_from_name=workspace.sender_name or workspace.name,
            reply_to_email=workspace.reply_to_email or workspace.tenant_email or workspace.office_email,
            created_by=request.user,
        )
        accept_url = f"{str(getattr(settings, 'FRONTEND_BASE_URL', 'https://syncworksapp.com')).rstrip('/')}/tenant/invite?code={invite.code}"
        subject = f"{workspace.name} invited you to SyncWorks"
        body = (
            f"Hello {tenant.first_name},\n\n"
            f"{workspace.name} invited you to connect to your tenant portal for "
            f"{tenant.property_name or 'your property'}{(' - ' + tenant.unit_label) if tenant.unit_label else ''}.\n\n"
            f"Invitation code: {invite.code}\nOpen: {accept_url}\n\n"
            f"This invitation expires {invite.expires_at:%B %d, %Y}.\n\n"
            f"{workspace.email_signature or workspace.sender_name or workspace.name}"
        )
        email = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "notifications@syncworksapp.com"),
            to=[tenant.email],
            reply_to=[invite.reply_to_email] if invite.reply_to_email else None,
        )
        try:
            email.send(fail_silently=False)
            invite.sent_at = timezone.now()
            invite.save(update_fields=["sent_at"])
            tenant.status = PMTenant.Status.INVITE_PENDING
            tenant.save(update_fields=["status", "updated_at"])
        except Exception:
            invite.status = PMTenantInvitation.Status.REVOKED
            invite.revoked_at = timezone.now()
            invite.save(update_fields=["status", "revoked_at"])
            return Response({"detail": "The invitation was created but email delivery failed. Check email configuration."}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(PMTenantInvitationSerializer(invite).data, status=status.HTTP_201_CREATED)


class PMTenantInvitationViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMTenantInvitationSerializer

    def get_queryset(self):
        return PMTenantInvitation.objects.filter(tenant__workspace__owner=self.request.user).select_related("tenant", "tenant__workspace")

    @action(detail=False, methods=["post"], url_path="accept")
    @transaction.atomic
    def accept(self, request):
        code = str(request.data.get("code") or "").strip().upper()
        invite = PMTenantInvitation.objects.select_for_update().select_related("tenant").filter(code=code).first()
        if not invite:
            return Response({"detail": "Invitation not found."}, status=status.HTTP_404_NOT_FOUND)
        if invite.status != PMTenantInvitation.Status.PENDING:
            return Response({"detail": "Invitation is no longer active."}, status=status.HTTP_409_CONFLICT)
        if invite.expires_at <= timezone.now():
            invite.status = PMTenantInvitation.Status.EXPIRED
            invite.save(update_fields=["status"])
            return Response({"detail": "Invitation has expired."}, status=status.HTTP_410_GONE)
        if request.user.email.lower() != invite.sent_to_email.lower():
            return Response({"detail": "Sign in with the invited email address."}, status=status.HTTP_403_FORBIDDEN)
        tenant = invite.tenant
        if invite.mode == PMTenantInvitation.Mode.TENANT_ONBOARDING:
            for field in ("first_name", "last_name", "phone"):
                value = request.data.get(field)
                if value is not None:
                    setattr(tenant, field, str(value).strip())
        tenant.user = request.user
        tenant.status = PMTenant.Status.CONNECTED
        tenant.save()
        invite.status = PMTenantInvitation.Status.ACCEPTED
        invite.accepted_at = timezone.now()
        invite.save(update_fields=["status", "accepted_at"])
        return Response({"detail": "Tenant account connected.", "tenant": PMTenantSerializer(tenant).data})
