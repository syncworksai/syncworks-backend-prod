from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models.personal_finance import FinanceAccount, FinanceConnection, FinanceLiability
from user_accounts.serializers.personal_finance import FinanceAccountSerializer, FinanceLiabilitySerializer
from user_accounts.services.finance_intelligence import build_finance_briefing, infer_recurring_obligations
from user_accounts.services.plaid_finance import sync_connection


def _decimal(value, *, required=False):
    if value in (None, ""):
        if required:
            raise ValueError("A numeric value is required.")
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Enter a valid number.") from exc


def _date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("Enter a valid date.") from exc


def _extra_monthly(request):
    raw = request.query_params.get("extra_monthly", request.data.get("extra_monthly", "0") if hasattr(request, "data") else "0")
    try:
        return max(Decimal("0"), Decimal(str(raw or "0")))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


class FinanceAutomationViewSet(viewsets.ViewSet):
    """Finance intelligence endpoints shared by the dashboard and SYNC Assist."""

    permission_classes = [IsAuthenticated]

    def list(self, request):
        return Response(build_finance_briefing(request.user, extra_monthly=_extra_monthly(request)))

    @action(detail=False, methods=["post"], url_path="refresh")
    def refresh(self, request):
        synced = 0
        errors = []

        connections = FinanceConnection.objects.filter(
            user=request.user,
            status=FinanceConnection.Status.ACTIVE,
        )
        for connection in connections:
            try:
                sync_connection(connection)
                synced += 1
            except Exception as exc:
                errors.append({"connection_id": connection.id, "detail": str(exc)})

        recurring = infer_recurring_obligations(request.user)
        payload = {
            "synced_connections": synced,
            "connection_errors": errors,
            "recurring": recurring,
            "briefing": build_finance_briefing(request.user, extra_monthly=_extra_monthly(request)),
        }
        return Response(payload, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="manual-card")
    @transaction.atomic
    def manual_card(self, request):
        """Create a manual revolving account and its liability in one transaction."""
        name = str(request.data.get("name") or "").strip()
        if not name:
            return Response({"detail": "Card name is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            balance = _decimal(request.data.get("balance"), required=True)
            credit_limit = _decimal(request.data.get("credit_limit"))
            minimum = _decimal(request.data.get("minimum_payment"))
            apr = _decimal(request.data.get("apr"))
            due_date = _date(request.data.get("next_payment_date") or request.data.get("due_date"))
            promo_end = _date(request.data.get("promo_apr_end_date"))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        metadata = {
            "source": "manual_card",
            "account_status": str(request.data.get("account_status") or "OPEN").upper(),
            "paid_this_cycle": bool(request.data.get("paid_this_cycle", False)),
        }
        if promo_end:
            metadata["promo_apr_end_date"] = promo_end.isoformat()
        promo_apr = request.data.get("promo_apr")
        if promo_apr not in (None, ""):
            try:
                metadata["promo_apr"] = str(_decimal(promo_apr))
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        account = FinanceAccount.objects.create(
            user=request.user,
            name=name,
            official_name=str(request.data.get("official_name") or ""),
            kind=FinanceAccount.Kind.CREDIT_CARD,
            current_balance=balance,
            credit_limit=credit_limit,
            is_manual=True,
            metadata=metadata,
        )
        liability = FinanceLiability.objects.create(
            user=request.user,
            account=account,
            name=name,
            kind=FinanceLiability.Kind.CREDIT_CARD,
            lender=str(request.data.get("lender") or ""),
            outstanding_balance=balance,
            minimum_payment=minimum,
            next_payment_amount=minimum,
            next_payment_date=due_date,
            apr=apr,
            is_manual=True,
            metadata={**metadata, "credit_limit": str(credit_limit) if credit_limit is not None else None},
        )
        return Response(
            {
                "account": FinanceAccountSerializer(account).data,
                "liability": FinanceLiabilitySerializer(liability).data,
            },
            status=status.HTTP_201_CREATED,
        )
