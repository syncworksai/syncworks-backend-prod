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


    def test_property_handoff_is_saved_without_creating_debts_or_payments(self):
        self.client.force_authenticate(self.owner)
        url = f"/api/v1/pm-hub/properties/{self.property.id}/handoff/"
        initial = self.client.get(url, **self.owner_headers())
        self.assertEqual(initial.status_code, 200, initial.data)
        self.assertEqual(initial.data["progress"]["completed"], 0)
        self.assertFalse(PMDocumentPacket.objects.filter(workspace=self.workspace, packet_type="PROPERTY_HANDOFF").exists())
        updated = self.client.patch(url, {
            "case_kind": "NEW_MANAGEMENT",
            "effective_date": "2026-03-01",
            "former_manager": {"name": "Prior PM", "email": "", "phone": "", "notice_sent_date": "2026-02-01"},
            "assistance": {
                "type": "HOUSING_VOUCHER",
                "administrator": "Local housing program",
                "administrator_website": "",
                "contact_email": "",
                "contract_status": "PENDING_APPROVAL",
                "payee_status": "SUBMITTED",
            },
            "opening_balances": [
                {"id": "hap-1", "type": "ASSISTANCE_AR", "amount": "78.00", "period": "2026-07",
                 "counterparty": "Voucher administrator", "evidence_status": "REPORTED",
                 "source_note": "Administrator statement: funds awaiting owner registration"},
                {"id": "deposit-1", "type": "SECURITY_DEPOSIT", "amount": "1500.00", "period": "2024-09",
                 "counterparty": "Former manager", "evidence_status": "DISPUTED",
                 "source_note": "Lease lists deposit; final accounting not provided"},
            ],
        }, format="json", **self.owner_headers())
        self.assertEqual(updated.status_code, 200, updated.data)
        self.assertEqual(updated.data["handoff"]["assistance"]["administrator"], "Local housing program")
        self.assertTrue(any(t["key"] == "provider_packet" for t in updated.data["checklist"]))
        self.assertEqual(PMLedgerEntry.objects.filter(tenant=self.tenant).count(), 0)
        closed = self.client.patch(url, {"status": "COMPLETED"}, format="json", **self.owner_headers())
        self.assertEqual(closed.status_code, 400, closed.data)
        self.assertEqual(self.client.get(url, **self.owner_headers()).data["handoff"]["status"], "IN_PROGRESS")

    def test_handoff_task_verification_requires_evidence_and_workspace_scope(self):
        self.client.force_authenticate(self.owner)
        url = f"/api/v1/pm-hub/properties/{self.property.id}/handoff/"
        bad = self.client.patch(url, {"tasks": {"rent_ledger": {"status": "VERIFIED", "note": ""}}},
                                format="json", **self.owner_headers())
        self.assertEqual(bad.status_code, 400, bad.data)
        good = self.client.patch(url, {"tasks": {"rent_ledger": {
            "status": "VERIFIED", "note": "Owner reconciled the dated ledger against bank records",
        }}}, format="json", **self.owner_headers())
        self.assertEqual(good.status_code, 200, good.data)
        self.assertEqual(good.data["progress"]["completed"], 1)
        self.client.force_authenticate(self.tenant_user)
        unauthorized = self.client.get(url, **self.owner_headers())
        self.assertEqual(unauthorized.status_code, 403, unauthorized.data)


    def test_original_rent_audit_requires_source_and_keeps_ledger(self):
        lease = self.create_active_lease()
        self.client.force_authenticate(self.owner)
        entry = PMLedgerEntry.objects.create(
            workspace=self.workspace, tenant=self.tenant, lease=lease, entry_date=lease.start_date,
            entry_type="PAYMENT", category="RENT_TENANT", amount=Decimal("750.00"),
            created_by=self.owner)
        url = f"/api/v1/pm-hub/billing/tenants/{self.tenant.id}/original-lease-rent/"
        amount = "1485.00"
        data = {"contract_rent": amount, "effective_date": str(lease.start_date),
                "source_note": "Original signed rental lease specifies $1485 monthly"}
        preview = self.client.post(url, data, format="json", **self.owner_headers())
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertFalse(preview.data["applied"])
        lease.refresh_from_db()
        self.assertNotEqual(lease.monthly_rent, Decimal(amount))
        blocked = self.client.post(url, {**data, "apply": True}, format="json", **self.owner_headers())
        self.assertEqual(blocked.status_code, 400, blocked.data)
        apply = self.client.post(url, {**data, "apply": True, "confirmed": True}, format="json", **self.owner_headers())
        self.assertEqual(apply.status_code, 200, apply.data)
        lease.refresh_from_db()
        self.assertEqual(lease.monthly_rent, Decimal(amount))
        entry.refresh_from_db()
        self.assertEqual(entry.amount, Decimal("750.00"))
        self.assertEqual(entry.entry_type, "PAYMENT")
        self.assertTrue(self.tenant.document_packets.filter(packet_type="ORIGINAL_LEASE_RENT_AUDIT").exists())

    def test_rent_increase_request_does_not_raise_current_lease_rent_without_approval(self):
        lease = self.create_active_lease()
        lease.section8 = True
        lease.housing_authority = "Local rental assistance"
        lease.save()
        self.client.force_authenticate(self.owner)
        url = f"/api/v1/pm-hub/properties/{self.property.id}/rent-changes/"
        initial = str(lease.monthly_rent)
        payload = {
            "tenant_id": self.tenant.id,
            "current_rent": initial, "requested_rent": "1650.00",
            "proposed_effective_date": "2027-11-01",
            "hap_anniversary_date": "2027-11-01",
        }
        res = self.client.post(url, payload, format="json", **self.owner_headers())
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data["schedule"]["administrator_request_deadline"], "2027-09-02")
        lease.refresh_from_db()
        self.assertEqual(str(lease.monthly_rent), initial)
        edit_url = f"/api/v1/pm-hub/properties/{self.property.id}/rent-changes/{res.data['plan']['id']}/"
        rejected = self.client.patch(edit_url, {"status": "APPROVED", "approved_rent": "1650.00",
                                                 "approval_date": "2027-10-01"}, format="json", **self.owner_headers())
        self.assertEqual(rejected.status_code, 400, rejected.data)
        lease.refresh_from_db()
        self.assertEqual(str(lease.monthly_rent), initial)
        self.assertEqual(PMLedgerEntry.objects.filter(tenant=self.tenant).count(), 0)

    def test_document_extraction_requires_human_confirmation_and_does_not_update_rent(self):
        from django.core.files.base import ContentFile
        from pm_workspace.document_models import PMPropertyDocument
        lease = self.create_active_lease()
        self.client.force_authenticate(self.owner)
        document = PMPropertyDocument.objects.create(
            workspace=self.workspace, property=self.property, tenant=self.tenant,
            category="LEASE", title="Original lease", status="ACTIVE",
            document=ContentFile(b"Monthly Rent: $1,485.00\nSecurity Deposit: $1,500.00\nLease Start: 03/01/2026", name="signed-lease.txt"),
            created_by=self.owner)
        url = f"/api/v1/pm-hub/properties/{self.property.id}/documents/{document.id}/intake/"
        result = self.client.post(url, {}, format="json", **self.owner_headers())
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(result.data["suggestions"]["monthly_rent"]["value"], "1485.00")
        lease.refresh_from_db()
        self.assertNotEqual(lease.monthly_rent, Decimal("1485.00"))
        reviewed = self.client.patch(url, {"verified_fields":{"monthly_rent":"1485.00"}},
                                      format="json", **self.owner_headers())
        self.assertEqual(reviewed.status_code, 200, reviewed.data)
        lease.refresh_from_db()
        self.assertNotEqual(lease.monthly_rent, Decimal("1485.00"))


    def test_external_document_request_requires_send_then_evidence_to_verify(self):
        self.client.force_authenticate(self.owner)
        from pm_workspace.document_models import PMPropertyDocument
        url=f"/api/v1/pm-hub/properties/{self.property.id}/document-requests/"
        request_data={
            "title":"Recorded deed confirmation", "recipient_role":"ASSISTANCE_ADMINISTRATOR",
            "recipient_name":"Assistance desk","recipient_email":"housing@example.net",
            "action":"PROVIDE_DOCUMENT","instructions":"Please confirm which recorded deed is required.",
            "due_date":(timezone.localdate()+timedelta(days=10)).isoformat()
        }
        created=self.client.post(url,request_data,format="json",**self.owner_headers())
        self.assertEqual(created.status_code,201,created.data)
        record=created.data["request"]
        self.assertEqual(record["status"],"DRAFT")
        req_url=f"{url}{record['id']}/"
        unauthorized_status=self.client.patch(req_url,{"status":"VERIFIED"},format="json",**self.owner_headers())
        self.assertEqual(unauthorized_status.status_code,409,unauthorized_status.data)
        self.assertEqual(len(mail.outbox),0)
        sent=self.client.post(req_url,{"operation":"SEND"},format="json",**self.owner_headers())
        self.assertEqual(sent.status_code,200,sent.data)
        self.assertEqual(len(mail.outbox),1)
        self.assertEqual(mail.outbox[0].to,["housing@example.net"])
        self.assertIn("not an electronic-signature",mail.outbox[0].body.lower())
        second=self.client.post(req_url,{"operation":"REMIND"},format="json",**self.owner_headers())
        self.assertEqual(second.status_code,429,second.data)
        # A received/signed/approved request cannot be verified from a bare click.
        no_evidence=self.client.patch(req_url,{"status":"VERIFIED"},format="json",**self.owner_headers())
        self.assertEqual(no_evidence.status_code,400,no_evidence.data)
        doc=PMPropertyDocument.objects.create(
            workspace=self.workspace,property=self.property,category="OWNERSHIP",
            title="Recorded deed",status="ACTIVE",created_by=self.owner
        )
        verified=self.client.patch(req_url,{
            "status":"VERIFIED","completion_document_id":doc.id,
            "completion_evidence":"Signed copy checked by property manager in official county register."
        },format="json",**self.owner_headers())
        self.assertEqual(verified.status_code,200,verified.data)
        self.assertEqual(verified.data["request"]["status"],"VERIFIED")
        resent=self.client.post(req_url,{"operation":"REMIND"},format="json",**self.owner_headers())
        self.assertEqual(resent.status_code,409,resent.data)
        self.client.force_authenticate(self.tenant_user)
        denied=self.client.get(url,**self.owner_headers())
        self.assertEqual(denied.status_code,403,denied.data)

    def test_email_document_suggestions_do_not_change_handoff_or_send_emails(self):
        self.client.force_authenticate(self.owner)
        url=f"/api/v1/pm-hub/properties/{self.property.id}/analyze-correspondence/"
        response=self.client.post(url,{
            "body":"We need proof of ownership and a recorded warranty deed. Please send an inspection report."
        },format="json",**self.owner_headers())
        self.assertEqual(response.status_code,200,response.data)
        self.assertFalse(response.data["stored"])
        keys=[row["checklist_key"] for row in response.data["suggestions"]]
        self.assertIn("ownership_authority",keys)
        self.assertIn("provider_inspection",keys)
        self.assertFalse(PMDocumentPacket.objects.filter(workspace=self.workspace,packet_type="PROPERTY_HANDOFF").exists())
        self.assertEqual(len(mail.outbox),0)


    def test_workspace_employee_permissions_are_property_scoped(self):
        other = PMProperty.objects.create(
            workspace=self.workspace,name="Other Property",address="400 Elsewhere",
            city="Montgomery",state="AL",zip="36104",created_by=self.owner
        )
        employee = User.objects.create_user(
            username="onboarding-employee",email="onboarding@example.com",password="safe-password-123"
        )
        self.client.force_authenticate(self.owner)
        url="/api/v1/pm-hub/access/team/"
        response=self.client.post(url,{"email":"onboarding@example.com","name":"Alex",
                    "role":"LEASING","permissions":["onboarding"],"property_ids":[self.property.id]},
                   format="json",**self.owner_headers())
        self.assertEqual(response.status_code,201,response.data)
        code=response.data["invitation_code"]
        self.client.force_authenticate(employee)
        blocked=self.client.get("/api/v1/pm-hub/dashboard/command-center/",**self.owner_headers())
        self.assertEqual(blocked.status_code,403,blocked.data)
        joined=self.client.post("/api/v1/pm-hub/access/team/accept/",{"code":code},format="json")
        self.assertEqual(joined.status_code,200,joined.data)
        self.client.force_authenticate(self.owner)
        wrong=self.client.post("/api/v1/pm-hub/access/tasks/",{
            "property_id":other.id,"assignee_id":response.data["member"]["id"],
            "title":"Start onboarding","category":"ONBOARDING"
        },format="json",**self.owner_headers())
        self.assertEqual(wrong.status_code,403,wrong.data)
        right=self.client.post("/api/v1/pm-hub/access/tasks/",{
            "property_id":self.property.id,"assignee_id":response.data["member"]["id"],
            "title":"Verify onboarding packet","category":"ONBOARDING"
        },format="json",**self.owner_headers())
        self.assertEqual(right.status_code,201,right.data)
        self.client.force_authenticate(employee)
        dashboard=self.client.get("/api/v1/pm-hub/access/team/dashboard/")
        self.assertEqual(dashboard.status_code,200,dashboard.data)
        self.assertEqual(len(dashboard.data["tasks"]),1)
        self.assertEqual(dashboard.data["properties"][0]["id"],self.property.id)
        self.assertFalse(dashboard.data["finance_access"])
        self.assertEqual(self.client.get("/api/v1/pm-hub/access/investors/statements/").status_code,403)

    def test_investor_cannot_see_draft_or_other_owner_statement(self):
        from pm_workspace.owner_models import PMPropertyOwner
        owner_record=PMPropertyOwner.objects.create(
            workspace=self.workspace,name="Oak Investor",email="inv@example.com",created_by=self.owner
        )
        owner_record.properties.add(self.property)
        investor=User.objects.create_user(username="test-investor",email="inv@example.com",password="safe-password-123")
        self.client.force_authenticate(self.owner)
        r=self.client.post("/api/v1/pm-hub/access/investors/",{"owner_id":owner_record.id},
                           format="json",**self.owner_headers())
        self.assertEqual(r.status_code,201,r.data)
        code=r.data["invitation_code"]
        payload={
            "owner_id":owner_record.id,"property_id":self.property.id,"period":"2026-09",
            "rent_received":"1000.00","management_fees":"100.00","expenses":"200.00",
            "reserve_change":"0.00","owner_payout":"700.00","status":"DRAFT",
        }
        saved=self.client.post("/api/v1/pm-hub/access/investors/statements/",payload,
                               format="json",**self.owner_headers())
        self.assertEqual(saved.status_code,201,saved.data)
        self.client.force_authenticate(investor)
        self.assertEqual(self.client.post("/api/v1/pm-hub/access/investors/accept/",{"code":code},
                                        format="json").status_code,200)
        start=self.client.get("/api/v1/pm-hub/access/investors/portfolio/")
        self.assertEqual(start.status_code,200,start.data)
        self.assertEqual(len(start.data["portfolios"]),1)
        self.assertEqual(start.data["portfolios"][0]["statements"],[])
        self.client.force_authenticate(self.owner)
        payload["status"]="SHARED"
        published=self.client.post("/api/v1/pm-hub/access/investors/statements/",payload,
                                   format="json",**self.owner_headers())
        self.assertEqual(published.status_code,200,published.data)
        self.client.force_authenticate(investor)
        shown=self.client.get("/api/v1/pm-hub/access/investors/portfolio/")
        self.assertEqual(len(shown.data["portfolios"][0]["statements"]),1)
        self.assertEqual(shown.data["portfolios"][0]["statements"][0]["status"],"SHARED")
        self.assertIsNone(shown.data["portfolios"][0]["statements"][0]["payout_date"])


    def test_property_360_flags_name_only_matches_until_confirmed_and_preserves_ledger(self):
        self.client.force_authenticate(self.owner)
        charge=PMLedgerEntry.objects.create(
            workspace=self.workspace,tenant=self.tenant,
            entry_date=timezone.localdate(),entry_type="CHARGE",category="RENT_TENANT",
            amount=Decimal("1250.00"),created_by=self.owner)
        receipt=PMLedgerEntry.objects.create(
            workspace=self.workspace,tenant=self.tenant,
            entry_date=timezone.localdate(),entry_type="PAYMENT",category="RENT_TENANT",
            amount=Decimal("500.00"),created_by=self.owner)
        url=f"/api/v1/pm-hub/properties/{self.property.id}/360/"
        before=self.client.get(url,**self.owner_headers())
        self.assertEqual(before.status_code,200,before.data)
        self.assertEqual(before.data["tenants"][0]["link_status"],"REVIEW_NAME_MATCH")
        self.assertEqual(before.data["accounting"]["posted_tenant_unpaid"],"750.00")
        link_url=f"/api/v1/pm-hub/properties/{self.property.id}/link-tenant/{self.tenant.id}/"
        rejected=self.client.post(link_url,{},format="json",**self.owner_headers())
        self.assertEqual(rejected.status_code,400,rejected.data)
        linked=self.client.post(link_url,{"confirmed":True},format="json",**self.owner_headers())
        self.assertEqual(linked.status_code,200,linked.data)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.property_id,self.property.id)
        after=self.client.get(url,**self.owner_headers())
        self.assertEqual(after.status_code,200,after.data)
        self.assertEqual(after.data["tenants"][0]["link_status"],"VERIFIED_RELATION")
        self.assertEqual(after.data["accounting"]["posted_tenant_unpaid"],"750.00")
        self.assertEqual(PMLedgerEntry.objects.get(pk=charge.id).amount,Decimal("1250.00"))
        self.assertEqual(PMLedgerEntry.objects.get(pk=receipt.id).amount,Decimal("500.00"))

    def test_property_360_never_matches_name_when_duplicate_property_names_exist(self):
        PMProperty.objects.create(workspace=self.workspace,name=self.property.name,
            address="500 Different Avenue",city="Montgomery",state="AL",zip="36104",created_by=self.owner)
        self.client.force_authenticate(self.owner)
        result=self.client.get(f"/api/v1/pm-hub/properties/{self.property.id}/360/",**self.owner_headers())
        self.assertEqual(result.status_code,200,result.data)
        self.assertEqual(result.data["tenants"],[])
        self.assertEqual(result.data["links"]["property_name_unique"],False)

    def test_tenant_link_blocks_conflicting_existing_lease_and_other_portfolio(self):
        lease=self.create_active_lease()
        other=PMProperty.objects.create(workspace=self.workspace,name="Another Unit",
            address="100 Other St",city="Montgomery",state="AL",zip="36104",created_by=self.owner)
        self.client.force_authenticate(self.owner)
        wrong=self.client.post(f"/api/v1/pm-hub/properties/{other.id}/link-tenant/{self.tenant.id}/",
            {"confirmed":True},format="json",**self.owner_headers())
        self.assertEqual(wrong.status_code,409,wrong.data)
        self.tenant.refresh_from_db()
        self.assertIsNone(self.tenant.property_id)
        self.client.force_authenticate(self.tenant_user)
        denied=self.client.get(f"/api/v1/pm-hub/properties/{self.property.id}/360/",
             **self.owner_headers())
        self.assertEqual(denied.status_code,403,denied.data)
