from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from pm_workspace.lifecycle_models import PMOccupancy
from pm_workspace.models import (
    PMDocumentPacket,
    PMLedgerEntry,
    PMLease,
    PMProperty,
    PMTenant,
    PMTenantInvitation,
    PMUnit,
    PMWorkspace,
)
from pm_workspace.workorder_models import PMWorkOrder


User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    FRONTEND_BASE_URL="https://syncworksapp.com",
)
class PMTenantVerticalSliceTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="pm-owner",
            email="owner@example.com",
            password="safe-password-123",
        )
        self.tenant_user = User.objects.create_user(
            username="pm-tenant",
            email="tenant@example.com",
            password="safe-password-123",
        )
        self.workspace = PMWorkspace.objects.create(
            owner=self.owner,
            name="Blue Ridge Property Management",
            office_email="office@example.com",
            tenant_email="tenants@example.com",
        )
        self.property = PMProperty.objects.create(
            workspace=self.workspace,
            name="Oak Terrace",
            address="100 Oak Street",
            city="Montgomery",
            state="AL",
            zip="36104",
            created_by=self.owner,
        )
        self.unit = PMUnit.objects.create(
            workspace=self.workspace,
            property=self.property,
            label="2B",
            market_rent=Decimal("1250.00"),
        )
        self.tenant = PMTenant.objects.create(
            workspace=self.workspace,
            first_name="Taylor",
            last_name="Tenant",
            email="tenant@example.com",
            move_in_date=timezone.localdate(),
            property_name=self.property.name,
            unit_label=self.unit.label,
            monthly_rent=Decimal("1250.00"),
            created_by=self.owner,
        )

    def owner_headers(self):
        return {"HTTP_X_PM_WORKSPACE_ID": str(self.workspace.id)}

    def create_active_lease(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            "/api/v1/pm-hub/leases/",
            {
                "tenant": self.tenant.id,
                "unit": self.unit.id,
                "term": PMLease.Term.TWELVE_MONTH,
                "start_date": timezone.localdate(),
                "end_date": timezone.localdate() + timedelta(days=364),
                "monthly_rent": "1250.00",
                "security_deposit": "1250.00",
                "status": "ACTIVE",
            },
            format="json",
            **self.owner_headers(),
        )
        self.assertEqual(response.status_code, 201, response.data)
        return PMLease.objects.get(pk=response.data["id"])

    def connect_tenant(self):
        self.client.force_authenticate(self.owner)
        response = self.client.post(
            f"/api/v1/pm-hub/tenants/{self.tenant.id}/send-invite/",
            {"mode": PMTenantInvitation.Mode.TENANT_ONBOARDING},
            format="json",
            **self.owner_headers(),
        )
        self.assertEqual(response.status_code, 201, response.data)
        invite = PMTenantInvitation.objects.get(pk=response.data["id"])

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(f"/tenant/accept?code={invite.code}", mail.outbox[0].body)

        self.client.force_authenticate(self.tenant_user)
        response = self.client.post(
            "/api/v1/pm-hub/tenant-invitations/accept/",
            {"code": invite.code.lower()},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.user, self.tenant_user)
        self.assertEqual(self.tenant.status, PMTenant.Status.CONNECTED)

    def test_lease_creation_establishes_active_occupancy(self):
        lease = self.create_active_lease()

        occupancy = PMOccupancy.objects.get(tenant=self.tenant)
        self.assertEqual(occupancy.workspace, self.workspace)
        self.assertEqual(occupancy.property, self.property)
        self.assertEqual(occupancy.unit, self.unit)
        self.assertEqual(occupancy.lease, lease)
        self.assertEqual(occupancy.status, PMOccupancy.Status.ACTIVE)

        self.unit.refresh_from_db()
        self.assertEqual(self.unit.availability, PMUnit.Availability.OCCUPIED)

    def test_connected_tenant_uses_pm_workspace_account_and_communications(self):
        lease = self.create_active_lease()
        self.connect_tenant()
        PMLedgerEntry.objects.create(
            workspace=self.workspace,
            tenant=self.tenant,
            lease=lease,
            entry_date=timezone.localdate(),
            entry_type=PMLedgerEntry.EntryType.CHARGE,
            amount=Decimal("1250.00"),
            category="RENT",
            memo="September rent",
            created_by=self.owner,
        )
        PMDocumentPacket.objects.create(
            workspace=self.workspace,
            tenant=self.tenant,
            lease=lease,
            packet_type="LEASE",
            template_name="Residential lease",
            status=PMDocumentPacket.Status.SENT,
        )

        self.client.force_authenticate(self.tenant_user)
        account_response = self.client.get("/api/v1/pm-hub/billing/my-account/")
        self.assertEqual(account_response.status_code, 200, account_response.data)
        self.assertEqual(account_response.data["account"]["amount_due"], "1250.00")
        self.assertEqual(account_response.data["property_name"], "Oak Terrace")
        self.assertEqual(account_response.data["unit_label"], "2B")
        self.assertEqual(account_response.data["lease"]["id"], lease.id)
        self.assertEqual(account_response.data["documents"][0]["template_name"], "Residential lease")

        message_response = self.client.post(
            "/api/v1/pm-hub/tenant-portal/communications/",
            {"action": "MESSAGE", "subject": "Lease question", "body": "Please confirm my due date."},
            format="json",
        )
        self.assertEqual(message_response.status_code, 201, message_response.data)

        maintenance_response = self.client.post(
            "/api/v1/pm-hub/tenant-portal/communications/",
            {
                "action": "MAINTENANCE",
                "subject": "Kitchen faucet leak",
                "description": "The kitchen faucet is dripping continuously.",
                "category": "PLUMBING",
                "priority": PMWorkOrder.Priority.ROUTINE,
                "permission_to_enter": True,
            },
            format="json",
        )
        self.assertEqual(maintenance_response.status_code, 201, maintenance_response.data)
        work_order = PMWorkOrder.objects.get(pk=maintenance_response.data["work_order_id"])
        self.assertEqual(work_order.workspace, self.workspace)
        self.assertEqual(work_order.tenant, self.tenant)
        self.assertEqual(work_order.property, self.property)
        self.assertEqual(work_order.unit, self.unit)
        self.assertEqual(work_order.source, PMWorkOrder.Source.TENANT_PORTAL)

    def test_invitation_rejects_a_different_signed_in_email(self):
        self.client.force_authenticate(self.owner)
        invite_response = self.client.post(
            f"/api/v1/pm-hub/tenants/{self.tenant.id}/send-invite/",
            {"mode": PMTenantInvitation.Mode.TENANT_ONBOARDING},
            format="json",
            **self.owner_headers(),
        )
        invite = PMTenantInvitation.objects.get(pk=invite_response.data["id"])
        other_user = User.objects.create_user(
            username="wrong-tenant",
            email="wrong@example.com",
            password="safe-password-123",
        )

        self.client.force_authenticate(other_user)
        response = self.client.post(
            "/api/v1/pm-hub/tenant-invitations/accept/",
            {"code": invite.code},
            format="json",
        )

        self.assertEqual(response.status_code, 403, response.data)
        self.tenant.refresh_from_db()
        self.assertIsNone(self.tenant.user)
