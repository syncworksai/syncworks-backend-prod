from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import PMProperty, PMTenant, PMTenantInvitation, PMWorkspace
from .serializers import PMPropertySerializer, PMTenantInvitationSerializer, PMTenantSerializer, PMWorkspaceSerializer


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


class PMWorkspaceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = PMWorkspaceSerializer

    def get_queryset(self):
        return PMWorkspace.objects.filter(owner=self.request.user).order_by("name", "id")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=False, methods=["get", "patch"], url_path="current")
    def current(self, request):
        workspace_id = request.headers.get("X-PM-Workspace-ID") or request.query_params.get("workspace_id")
        workspace = _workspace_for_user(request.user, workspace_id)
        if request.method == "GET":
            if not workspace:
                return Response({"detail": "No PM workspace exists yet."}, status=status.HTTP_404_NOT_FOUND)
            return Response(self.get_serializer(workspace).data)

        if workspace:
            serializer = self.get_serializer(workspace, data=request.data, partial=True)
        else:
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
            tenant.invitations.filter(status=PMTenantInvitation.Status.PENDING).update(
                status=PMTenantInvitation.Status.REVOKED,
                revoked_at=timezone.now(),
            )
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

        tenant.invitations.filter(status=PMTenantInvitation.Status.PENDING).update(
            status=PMTenantInvitation.Status.REVOKED,
            revoked_at=timezone.now(),
        )
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
            f"Invitation code: {invite.code}\n"
            f"Open: {accept_url}\n\n"
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
