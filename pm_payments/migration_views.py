"""Shared five-stage payment migration guidance for Business and PM.

Never activates charges, processor credentials, rent checkout or transfers.
Connected-account capability is processor-verified; other steps are
owner-attested and/or manually reviewed with conspicuous audit limitations.
"""
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.viewsets.stripe_connect import _require_business_and_access, _is_platform_admin
from user_accounts.models.stripe_connect import StripeConnectProfile
from .models import PMCollectionSetup, PaymentMigrationPlan

TEST_ITEMS = (
    "customer_charged",
    "platform_fee_accounted",
    "provider_transfer_confirmed",
    "bank_deposit_verified",
    "receipt_and_ledger_matched",
    "failed_or_refunded_handled",
)
UPDATABLE = {
    "workspace_reviewed", "current_processor", "current_monthly_fees",
    "current_monthly_transactions", "average_payout_days",
    "monthly_reconciliation_hours", "costs_reviewed", "test_evidence",
    "test_notes", "request_test_review", "request_switch",
}


def _decimal(value, field, max_value, places):
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > max_value:
            raise ValueError()
        unit = Decimal("1").scaleb(-places)
        if number != number.quantize(unit):
            raise ValueError()
        return number
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({field: "Enter a non-negative amount with valid precision."})


def _is_connection_verified(business, setup):
    profile = StripeConnectProfile.objects.filter(business=business).first()
    capable = bool(
        business.stripe_connect_account_id and profile
        and profile.charges_enabled and profile.payouts_enabled
    )
    # PM legal/account review is deliberately additional; the business account
    # alone does not prove which PM portfolio or trust bank owns incoming rent.
    if setup and setup.method == PMCollectionSetup.Method.STRIPE_CONNECT:
        capable = capable and bool(setup.trust_account_reviewed_at)
    if setup and setup.method in (PMCollectionSetup.Method.EXTERNAL, PMCollectionSetup.Method.MANUAL):
        capable = False
    return capable


def _summary(business, plan):
    setup = PMCollectionSetup.objects.filter(business_id=business.id).first()
    bank_ready = _is_connection_verified(business, setup)
    checks = plan.test_evidence or {}
    evidence_complete = all(checks.get(key) is True for key in TEST_ITEMS)
    stages = [
        {"key": "join", "title": "Join and keep the existing processor",
         "complete": bool(plan.workspace_reviewed_at),
         "detail": "Complete business/PM setup, employees and existing records without disrupting collection."},
        {"key": "costs", "title": "Compare existing processing and operating costs",
         "complete": bool(plan.costs_reviewed_at),
         "detail": "Document processor, fees, payout delays, returned payments and reconciliation time."},
        {"key": "bank", "title": "Verify receiving bank and processor",
         "complete": bank_ready,
         "detail": "Processor-reported charges and payouts must be enabled; PM also needs appropriate trust-account review."},
        {"key": "test", "title": "Review a controlled end-to-end payment test",
         "complete": bool(plan.founder_test_reviewed_at),
         "detail": "Document customer charge, platform fee, transfer, bank deposit, receipt, ledger and refund/failure test."},
        {"key": "switch", "title": "Switch collections only after approval",
         "complete": False,
         "detail": "Owner can request migration; live checkout remains disabled until legal and actual settlement verification."},
    ]
    return {
        "business_id": business.id,
        "business_name": business.name,
        "stages": stages,
        "completed_count": sum(int(s["complete"]) for s in stages),
        "current_processor": plan.current_processor,
        "current_monthly_fees": str(plan.current_monthly_fees) if plan.current_monthly_fees is not None else "",
        "current_monthly_transactions": plan.current_monthly_transactions,
        "average_payout_days": str(plan.average_payout_days) if plan.average_payout_days is not None else "",
        "monthly_reconciliation_hours": str(plan.monthly_reconciliation_hours) if plan.monthly_reconciliation_hours is not None else "",
        "workspace_reviewed": bool(plan.workspace_reviewed_at),
        "costs_reviewed": bool(plan.costs_reviewed_at),
        "bank_ready": bank_ready,
        "selected_pm_payment_method": setup.method if setup else "UNCONFIGURED",
        "test_evidence": {key: checks.get(key) is True for key in TEST_ITEMS},
        "test_evidence_complete": evidence_complete,
        "test_notes": plan.test_notes,
        "test_review_requested": bool(plan.test_review_requested_at),
        "founder_test_reviewed": bool(plan.founder_test_reviewed_at),
        "founder_test_notes": plan.founder_test_notes,
        "switch_requested": bool(plan.switch_requested_at),
        "online_collection_enabled": False,
        "live_activation_requires_release": True,
        "updated_at": plan.updated_at,
    }


class PaymentMigrationPlanAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business, _, error = _require_business_and_access(request)
        if error:
            return error
        plan, _ = PaymentMigrationPlan.objects.get_or_create(business=business)
        return Response(_summary(business, plan))

    def patch(self, request):
        business, _, error = _require_business_and_access(request)
        if error:
            return error
        values = request.data or {}
        if set(values) - UPDATABLE:
            raise ValidationError({"detail": "Unsupported migration plan field."})
        with transaction.atomic():
            plan, _ = PaymentMigrationPlan.objects.select_for_update().get_or_create(business=business)
            baseline_fields = (
                "current_processor", "current_monthly_fees", "current_monthly_transactions",
                "average_payout_days", "monthly_reconciliation_hours",
            )
            old_baseline = tuple(getattr(plan, field) for field in baseline_fields)
            old_notes = plan.test_notes
            if "current_processor" in values:
                v = str(values["current_processor"] or "").strip()
                if len(v) > 100:
                    raise ValidationError({"current_processor": "Maximum 100 characters."})
                plan.current_processor = v
            if "current_monthly_fees" in values:
                plan.current_monthly_fees = _decimal(values["current_monthly_fees"], "current_monthly_fees", Decimal("9999999999"), 2)
            if "current_monthly_transactions" in values:
                raw = values["current_monthly_transactions"]
                if raw is None or raw == "":
                    plan.current_monthly_transactions = None
                else:
                    try:
                        number = int(str(raw))
                        if number < 0 or number > 1000000 or str(raw).strip() != str(number):
                            raise ValueError()
                    except (ValueError, TypeError):
                        raise ValidationError({"current_monthly_transactions": "Enter a non-negative whole number."})
                    plan.current_monthly_transactions = number
            for field, limit in (("average_payout_days", Decimal("9999")), ("monthly_reconciliation_hours", Decimal("9999"))):
                if field in values:
                    setattr(plan, field, _decimal(values[field], field, limit, 1))
            if "workspace_reviewed" in values:
                if not isinstance(values["workspace_reviewed"], bool):
                    raise ValidationError({"workspace_reviewed": "Use true or false."})
                plan.workspace_reviewed_at = timezone.now() if values["workspace_reviewed"] else None
            if "costs_reviewed" in values:
                if not isinstance(values["costs_reviewed"], bool):
                    raise ValidationError({"costs_reviewed": "Use true or false."})
                if values["costs_reviewed"] and (not plan.workspace_reviewed_at or not plan.current_processor or plan.current_monthly_fees is None):
                    raise ValidationError({"costs_reviewed": "Confirm workspace setup, current provider and monthly costs first."})
                plan.costs_reviewed_at = timezone.now() if values["costs_reviewed"] else None
            if "test_evidence" in values:
                evidence = values["test_evidence"]
                if not isinstance(evidence, dict) or set(evidence) - set(TEST_ITEMS) or not all(isinstance(v, bool) for v in evidence.values()):
                    raise ValidationError({"test_evidence": "Use boolean values for the six documented payment checks."})
                plan.test_evidence = {**(plan.test_evidence or {}), **evidence}
                plan.test_review_requested_at = None
                plan.founder_test_reviewed_at = None
                plan.founder_test_reviewer_id = None
                plan.switch_requested_at = None
            if "test_notes" in values:
                v = str(values["test_notes"] or "").strip()
                if len(v) > 3000:
                    raise ValidationError({"test_notes": "Maximum 3000 characters."})
                plan.test_notes = v
            # Any edited cost baseline or test reference invalidates earlier manual
            # reviewer sign-off. Never retain a stale migration or payout assertion.
            baseline_changed = old_baseline != tuple(getattr(plan, field) for field in baseline_fields)
            evidence_changed = "test_evidence" in values or ("test_notes" in values and old_notes != plan.test_notes)
            if baseline_changed or evidence_changed or not plan.workspace_reviewed_at:
                plan.test_review_requested_at = None
                plan.founder_test_reviewed_at = None
                plan.founder_test_reviewer_id = None
                plan.founder_test_notes = ""
                plan.switch_requested_at = None
                if baseline_changed and values.get("costs_reviewed") is not True:
                    plan.costs_reviewed_at = None
            if values.get("request_test_review") is True:
                if not plan.costs_reviewed_at or not _is_connection_verified(business, PMCollectionSetup.objects.filter(business_id=business.id).first()):
                    raise ValidationError({"request_test_review": "Complete cost review and connect a verified receiving account first."})
                if not all((plan.test_evidence or {}).get(key) is True for key in TEST_ITEMS) or not plan.test_notes:
                    raise ValidationError({"request_test_review": "Complete all payment evidence checks and add a reference."})
                plan.test_review_requested_at = timezone.now()
            if "request_switch" in values:
                if values["request_switch"] is not True:
                    raise ValidationError({"request_switch": "Only a switch request is allowed."})
                if not plan.founder_test_reviewed_at or not _is_connection_verified(business, PMCollectionSetup.objects.filter(business_id=business.id).first()):
                    raise ValidationError({"request_switch": "Verified account capabilities and founder test review are required."})
                plan.switch_requested_at = timezone.now()
            plan.updated_by_id = request.user.id
            plan.save()
        return Response(_summary(business, plan))


class PaymentMigrationFounderReviewAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _is_platform_admin(request.user):
            return Response({"detail": "Only a platform founder/admin can review test evidence."}, status=403)
        business, _, error = _require_business_and_access(request)
        if error:
            return error
        notes = str(request.data.get("notes") or "").strip()
        if not notes or len(notes) > 3000:
            raise ValidationError({"notes": "Founder review notes are required (max 3000 characters)."})
        plan = PaymentMigrationPlan.objects.filter(business=business).first()
        if not plan or not plan.test_review_requested_at:
            return Response({"detail": "Owner has not submitted test evidence for review."}, status=409)
        if not all((plan.test_evidence or {}).get(key) is True for key in TEST_ITEMS):
            return Response({"detail": "The six evidence checks are incomplete."}, status=409)
        if not _is_connection_verified(business, PMCollectionSetup.objects.filter(business_id=business.id).first()):
            return Response({"detail": "Bank/processor capabilities are no longer verified."}, status=409)
        plan.founder_test_reviewed_at = timezone.now()
        plan.founder_test_reviewer_id = request.user.id
        plan.founder_test_notes = notes
        plan.save(update_fields=["founder_test_reviewed_at", "founder_test_reviewer_id", "founder_test_notes", "updated_at"])
        return Response(_summary(business, plan))
