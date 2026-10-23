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


    def test_monthly_section8_reconciliation_preserves_history_and_is_idempotent(self):
        lease = self.create_active_lease()
        lease.section8 = True
        lease.monthly_rent = Decimal("1485.00")
        lease.tenant_portion = Decimal("1485.00")
        lease.assistance_portion = Decimal("0.00")
        lease.save()
        self.client.force_authenticate(self.owner)
        month = "2026-08"
        for entry_type, amount, category in (
            ("CHARGE", "1400.00", "RENT_TENANT"),
            ("CHARGE", "50.00", "LATE_FEE"),
            ("PAYMENT", "750.00", "RENT_TENANT"),
        ):
            PMLedgerEntry.objects.create(
                workspace=self.workspace, tenant=self.tenant, lease=lease,
                entry_date="2026-08-06", entry_type=entry_type,
                amount=Decimal(amount), category=category, created_by=self.owner,
            )
        payload = {
            "month": month, "contract_rent": "1485.00",
            "tenant_portion": "1485.00", "housing_portion": "0.00",
            "source_note": "MHA confirmed August tenant full-rent obligation",
        }
        url = f"/api/v1/pm-hub/billing/tenants/{self.tenant.id}/reconcile-month/"
        count = PMLedgerEntry.objects.filter(tenant=self.tenant).count()
        preview = self.client.post(url, payload, format="json", **self.owner_headers())
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertFalse(preview.data["applied"])
        self.assertEqual(preview.data["tenant_charge_adjustment"], "85.00")
        self.assertEqual(PMLedgerEntry.objects.filter(tenant=self.tenant).count(), count)
        blocked = self.client.post(url, {**payload, "apply": True}, format="json", **self.owner_headers())
        self.assertEqual(blocked.status_code, 400, blocked.data)
        applied = self.client.post(url, {**payload, "apply": True, "confirmed": True}, format="json", **self.owner_headers())
        self.assertEqual(applied.status_code, 200, applied.data)
        self.assertEqual(applied.data["preserved_late_fees"], "50.00")
        self.assertEqual(PMLedgerEntry.objects.filter(tenant=self.tenant, entry_type="PAYMENT").count(), 1)
        again = self.client.post(url, {**payload, "apply": True, "confirmed": True}, format="json", **self.owner_headers())
        self.assertEqual(again.status_code, 200, again.data)
        self.assertEqual(again.data["tenant_charge_adjustment"], "0.00")
        self.assertEqual(PMLedgerEntry.objects.filter(tenant=self.tenant).count(), count + 1)

    def test_reconcile_abatement_only_bills_confirmed_tenant_portion(self):
        lease = self.create_active_lease()
        lease.section8 = True
        lease.monthly_rent = Decimal("1485.00")
        lease.save()
        self.client.force_authenticate(self.owner)
        url = f"/api/v1/pm-hub/billing/tenants/{self.tenant.id}/reconcile-month/"
        payload = {
            "month": "2026-10", "contract_rent": "1485.00",
            "tenant_portion": "1108.00", "housing_portion": "0.00",
            "exclusion_reason": "MHA housing share abated from October 1; not assessed to tenant",
            "source_note": "October inspection abatement and September rent determination",
            "apply": True, "confirmed": True,
        }
        response = self.client.post(url, payload, format="json", **self.owner_headers())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["excluded_from_charges"], "377.00")
        self.assertEqual(PMLedgerEntry.objects.filter(tenant=self.tenant, category="RENT_HOUSING").count(), 0)
        self.assertEqual(PMLedgerEntry.objects.get(tenant=self.tenant, category="RENT_TENANT").amount, Decimal("1108.00"))


    def test_oldest_first_allocates_tenant_receipts_without_touching_hap_or_receipt_dates(self):
        lease = self.create_active_lease()
        lease.section8 = True
        lease.save()
        self.client.force_authenticate(self.owner)
        for day, typ, category, method, amt in [
            ("2026-03-01", "CHARGE", "RENT_TENANT", "", "1407.00"),
            ("2026-03-01", "CHARGE", "RENT_HOUSING", "", "78.00"),
            ("2026-04-01", "CHARGE", "RENT_TENANT", "", "1407.00"),
            ("2026-03-15", "PAYMENT", "RENT_TENANT", "OTHER", "800.00"),
            ("2026-04-10", "PAYMENT", "RENT_TENANT", "OTHER", "750.00"),
        ]:
            PMLedgerEntry.objects.create(
                workspace=self.workspace, tenant=self.tenant, lease=lease, entry_date=day,
                entry_type=typ, category=category, payment_method=method,
                amount=Decimal(amt), created_by=self.owner,
            )
        before = list(PMLedgerEntry.objects.filter(tenant=self.tenant).values_list("id", "entry_date"))
        res = self.client.get(f"/api/v1/pm-hub/billing/tenants/{self.tenant.id}/allocations/", **self.owner_headers())
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["payment_dates_unchanged"], True)
        self.assertEqual(res.data["housing_unpaid"], "78.00")
        self.assertEqual(res.data["tenant_unpaid"], "1264.00")
        payment_applied = [row for row in res.data["allocations"] if row["source_type"] == "PAYMENT"]
        self.assertEqual([v["amount"] for v in payment_applied], ["800.00", "607.00", "143.00"])
        self.assertEqual([v["charge_month"] for v in payment_applied], ["2026-03", "2026-03", "2026-04"])
        self.assertEqual(before, list(PMLedgerEntry.objects.filter(tenant=self.tenant).values_list("id", "entry_date")))

    def test_external_hap_and_deposit_claims_never_create_ledger_payments(self):
        self.client.force_authenticate(self.owner)
        url = f"/api/v1/pm-hub/billing/tenants/{self.tenant.id}/external-evidence/"
        for category, amount in (
            ("HAP_PAID_TO_FORMER_MANAGER", "312.00"),
            ("HAP_ON_HOLD", "455.00"),
            ("DEPOSIT_APPLIED_CLAIM", "1500.00"),
        ):
            response = self.client.post(url, {
                "category": category, "period": "2026-03", "amount": amount,
                "evidence_status": "REPORTED", "note": "Written statement pending full reconciliation",
            }, format="json", **self.owner_headers())
            self.assertEqual(response.status_code, 201, response.data)
            self.assertFalse(response.data["affects_ledger_balance"])
        self.assertEqual(PMLedgerEntry.objects.filter(tenant=self.tenant).count(), 0)
        records = self.client.get(url, **self.owner_headers())
        self.assertEqual(records.status_code, 200, records.data)
        self.assertEqual(len(records.data["records"]), 3)


    def test_reviewed_late_fee_needs_unpaid_tenant_rent_and_cannot_duplicate(self):
        lease = self.create_active_lease()
        lease.section8 = True
        lease.save()
        self.client.force_authenticate(self.owner)
        PMLedgerEntry.objects.create(
            workspace=self.workspace, tenant=self.tenant, lease=lease,
            entry_date="2026-06-01", entry_type="CHARGE",
            amount=Decimal("1407.00"), category="RENT_TENANT",
            created_by=self.owner,
        )
        payload = {"month": "2026-06", "amount": "50.00", "due_day": 1,
                   "grace_days": 0, "source_note": "Signed lease says $50 after first"}
        url = f"/api/v1/pm-hub/billing/tenants/{self.tenant.id}/verified-late-fee/"
        preview = self.client.post(url, payload, format="json", **self.owner_headers())
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(preview.data["eligible_for_review"], True)
        self.assertEqual(preview.data["unpaid_tenant_rent_at_grace"], "1407.00")
        self.assertEqual(PMLedgerEntry.objects.filter(tenant=self.tenant).count(), 1)
        blocked = self.client.post(url, {**payload, "apply": True}, format="json", **self.owner_headers())
        self.assertEqual(blocked.status_code, 400, blocked.data)
        applied = self.client.post(url, {**payload, "apply": True, "confirmed": True,
                                         "lease_verified": True}, format="json", **self.owner_headers())
        self.assertEqual(applied.status_code, 200, applied.data)
        self.assertTrue(applied.data["applied"])
        again = self.client.post(url, {**payload, "apply": True, "confirmed": True,
                                       "lease_verified": True}, format="json", **self.owner_headers())
        self.assertEqual(again.status_code, 409, again.data)
        self.assertEqual(PMLedgerEntry.objects.filter(tenant=self.tenant, category="LATE_FEE").count(), 1)
