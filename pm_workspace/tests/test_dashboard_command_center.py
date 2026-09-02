from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APITestCase

from user_accounts.models import User

from pm_workspace.communication_models import PMConversation
from pm_workspace.document_models import PMPropertyDocument
from pm_workspace.lifecycle_models import PMTenantCase
from pm_workspace.models import PMDocumentPacket, PMLedgerEntry, PMLease, PMProject, PMProperty, PMTenant, PMUnit, PMWorkspace
from pm_workspace.workorder_models import PMWorkOrder


class PMCommandCenterTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="pm-dashboard@example.com",
            email="pm-dashboard@example.com",
            password="Password123!",
        )
        self.workspace = PMWorkspace.objects.create(owner=self.user, name="Dashboard Portfolio")
        self.property = PMProperty.objects.create(
            workspace=self.workspace,
            name="Roxana",
            address="3380 Roxana Road",
            city="Montgomery",
            state="AL",
            zip="36108",
            status=PMProperty.Status.AT_RISK,
        )
        self.occupied_unit = PMUnit.objects.create(
            workspace=self.workspace,
            property=self.property,
            label="A",
            availability=PMUnit.Availability.OCCUPIED,
        )
        PMUnit.objects.create(
            workspace=self.workspace,
            property=self.property,
            label="B",
            availability=PMUnit.Availability.AVAILABLE,
        )
        self.tenant = PMTenant.objects.create(
            workspace=self.workspace,
            first_name="Jordan",
            last_name="Lee",
            email="jordan@example.com",
        )
        self.lease = PMLease.objects.create(
            workspace=self.workspace,
            tenant=self.tenant,
            unit=self.occupied_unit,
            start_date=timezone.localdate() - timedelta(days=300),
            end_date=timezone.localdate() + timedelta(days=3),
            monthly_rent=Decimal("1000.00"),
            section8=True,
            housing_authority="Montgomery Housing Authority",
            status="ACTIVE",
        )
        PMLedgerEntry.objects.create(
            workspace=self.workspace,
            tenant=self.tenant,
            lease=self.lease,
            entry_date=timezone.localdate().replace(day=1),
            entry_type=PMLedgerEntry.EntryType.CHARGE,
            amount=Decimal("1000.00"),
            category="RENT",
        )
        PMLedgerEntry.objects.create(
            workspace=self.workspace,
            tenant=self.tenant,
            lease=self.lease,
            entry_date=timezone.localdate(),
            entry_type=PMLedgerEntry.EntryType.PAYMENT,
            amount=Decimal("800.00"),
            category="RENT",
            payment_method=PMLedgerEntry.Method.HOUSING_AUTHORITY,
        )
        PMWorkOrder.objects.create(
            workspace=self.workspace,
            property=self.property,
            unit=self.occupied_unit,
            category="MAKE_READY",
            title="Repair entry door",
            description="Door will not latch.",
            priority=PMWorkOrder.Priority.URGENT,
            status=PMWorkOrder.Status.SCHEDULED,
            scheduled_for=timezone.now() + timedelta(days=1),
        )
        PMProject.objects.create(
            workspace=self.workspace,
            property=self.property,
            title="Exterior paint",
            status=PMProject.Status.IN_PROGRESS,
            target_date=timezone.localdate() + timedelta(days=2),
            blocker="Waiting for owner approval",
        )
        PMTenantCase.objects.create(
            workspace=self.workspace,
            tenant=self.tenant,
            property=self.property,
            case_type=PMTenantCase.CaseType.EVICTION,
            status=PMTenantCase.Status.OPEN,
            opened_date=timezone.localdate(),
            current_balance=Decimal("200.00"),
        )
        PMDocumentPacket.objects.create(
            workspace=self.workspace,
            tenant=self.tenant,
            lease=self.lease,
            packet_type="SECTION8_RECERTIFICATION",
            housing_authority="Montgomery Housing Authority",
            template_name="Recertification packet",
            status=PMDocumentPacket.Status.SENT,
        )
        PMPropertyDocument.objects.create(
            workspace=self.workspace,
            property=self.property,
            tenant=self.tenant,
            lease=self.lease,
            category=PMPropertyDocument.Category.SECTION8,
            title="Housing assistance certification",
            status=PMPropertyDocument.Status.SUBMITTED,
            expiration_date=timezone.localdate() + timedelta(days=4),
        )
        PMConversation.objects.create(
            workspace=self.workspace,
            category=PMConversation.Category.TENANT,
            status=PMConversation.Status.WAITING_REQUESTER,
            subject="Section 8 deed request",
            tenant=self.tenant,
            property=self.property,
        )
        self.client.force_authenticate(self.user)

    def get_dashboard(self):
        return self.client.get(
            "/api/v1/pm-hub/dashboard/command-center/",
            HTTP_X_PM_WORKSPACE_ID=str(self.workspace.id),
        )

    def test_command_center_returns_real_finance_operations_and_schedule(self):
        response = self.get_dashboard()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["kpis"]["properties"], 1)
        self.assertEqual(response.data["kpis"]["units"], 2)
        self.assertEqual(response.data["kpis"]["occupancy_rate"], 50)
        self.assertEqual(response.data["kpis"]["open_work_orders"], 1)
        self.assertEqual(response.data["kpis"]["make_ready"], 1)
        self.assertEqual(response.data["financials"]["month_revenue"], "800.00")
        self.assertEqual(response.data["financials"]["month_charges"], "1000.00")
        self.assertEqual(response.data["financials"]["collection_rate"], 80.0)
        self.assertEqual(response.data["financials"]["outstanding_balance"], "200.00")
        self.assertEqual(response.data["cases"]["evictions"], 1)
        self.assertEqual(response.data["section8"]["attention"], 3)
        self.assertGreaterEqual(response.data["schedule"]["week_count"], 4)
        self.assertEqual(response.data["active_work_orders"][0]["priority"], PMWorkOrder.Priority.URGENT)

    def test_command_center_is_scoped_to_the_requested_owner_workspace(self):
        other_user = User.objects.create_user(
            username="other-pm@example.com",
            email="other-pm@example.com",
            password="Password123!",
        )
        other_workspace = PMWorkspace.objects.create(owner=other_user, name="Other Portfolio")
        PMProperty.objects.create(
            workspace=other_workspace,
            name="Hidden Property",
            address="1 Hidden Street",
            city="Montgomery",
            state="AL",
            zip="36104",
        )

        response = self.client.get(
            "/api/v1/pm-hub/dashboard/command-center/",
            HTTP_X_PM_WORKSPACE_ID=str(other_workspace.id),
        )

        self.assertEqual(response.status_code, 403)

    def test_command_center_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.get("/api/v1/pm-hub/dashboard/command-center/")
        self.assertEqual(response.status_code, 401)
