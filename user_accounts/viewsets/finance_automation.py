from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models.personal_finance import FinanceAccount, FinanceConnection, FinanceLiability, FinanceObligation, FinanceTransaction
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

    @action(detail=False, methods=["get"], url_path="account-match-candidates")
    def account_match_candidates(self, request):
        manual = list(
            FinanceAccount.objects.filter(
                user=request.user,
                is_manual=True,
                provider_account_id="",
                is_hidden=False,
            ).values("id", "name", "official_name", "kind", "current_balance", "credit_limit")
        )
        connected = list(
            FinanceAccount.objects.filter(
                user=request.user,
                is_manual=False,
                is_hidden=False,
            ).exclude(provider_account_id="").values("id", "name", "official_name", "kind", "mask", "current_balance", "credit_limit", "connection_id")
        )
        return Response({"manual": manual, "connected": connected})

    @action(detail=False, methods=["post"], url_path="link-connected-account")
    @transaction.atomic
    def link_connected_account(self, request):
        try:
            manual_id = int(request.data.get("manual_account_id"))
            connected_id = int(request.data.get("connected_account_id"))
        except (TypeError, ValueError):
            return Response({"detail": "Choose a manual account and a connected account."}, status=status.HTTP_400_BAD_REQUEST)

        manual = FinanceAccount.objects.select_for_update().filter(
            id=manual_id,
            user=request.user,
            is_manual=True,
        ).first()
        connected = FinanceAccount.objects.select_for_update().filter(
            id=connected_id,
            user=request.user,
            is_manual=False,
        ).first()
        if not manual or not connected:
            return Response({"detail": "The selected accounts are not available to link."}, status=status.HTTP_404_NOT_FOUND)
        if manual.id == connected.id:
            return Response({"detail": "Choose two different accounts."}, status=status.HTTP_400_BAD_REQUEST)
        if manual.kind != connected.kind and manual.kind != FinanceAccount.Kind.OTHER:
            return Response({"detail": "Account types must match before linking."}, status=status.HTTP_400_BAD_REQUEST)

        manual_liability = FinanceLiability.objects.select_for_update().filter(user=request.user, account=manual).first()
        connected_liability = FinanceLiability.objects.select_for_update().filter(user=request.user, account=connected).first()

        # Move provider-backed child records before deleting the temporary connected account.
        FinanceTransaction.objects.filter(user=request.user, account=connected).update(account=manual)
        FinanceObligation.objects.filter(user=request.user, linked_account=connected).update(linked_account=manual)

        # Release the provider account ID from the temporary connected row before
        # assigning it to the manual row; the database enforces one provider account ID
        # per user.
        provider_account_id = connected.provider_account_id
        connected.provider_account_id = ""
        connected.save(update_fields=["provider_account_id", "updated_at"])

        # Convert the existing manual account into the provider-backed account so the user's
        # manually entered history/labels survive future syncs.
        manual.connection = connected.connection
        manual.provider_account_id = provider_account_id
        manual.official_name = connected.official_name or manual.official_name
        manual.kind = connected.kind or manual.kind
        manual.mask = connected.mask or manual.mask
        manual.currency = connected.currency or manual.currency
        if connected.current_balance is not None:
            manual.current_balance = connected.current_balance
        if connected.available_balance is not None:
            manual.available_balance = connected.available_balance
        if connected.credit_limit is not None:
            manual.credit_limit = connected.credit_limit
        manual.is_manual = False
        manual.metadata = {
            **(manual.metadata or {}),
            **(connected.metadata or {}),
            "linked_from_manual": True,
            "linked_connected_account_id": connected.id,
        }
        manual.save()

        if connected_liability and manual_liability:
            for field in [
                "name", "kind", "lender", "outstanding_balance", "original_principal",
                "minimum_payment", "next_payment_amount", "next_payment_date", "apr",
                "interest_rate", "origination_date", "maturity_date", "last_payment_amount",
                "last_payment_date", "property_address", "escrow_balance",
            ]:
                value = getattr(connected_liability, field)
                if value not in (None, ""):
                    setattr(manual_liability, field, value)
            manual_liability.is_manual = False
            manual_liability.metadata = {
                **(manual_liability.metadata or {}),
                **(connected_liability.metadata or {}),
                "linked_from_manual": True,
            }
            manual_liability.save()
            connected_liability.delete()
        elif connected_liability:
            connected_liability.account = manual
            connected_liability.is_manual = False
            connected_liability.metadata = {
                **(connected_liability.metadata or {}),
                "linked_from_manual": True,
            }
            connected_liability.save()

        connected.delete()
        manual.refresh_from_db()
        linked_liability = FinanceLiability.objects.filter(user=request.user, account=manual).first()
        return Response({
            "account": FinanceAccountSerializer(manual).data,
            "liability": FinanceLiabilitySerializer(linked_liability).data if linked_liability else None,
            "detail": "Connected account linked to the existing Finance record.",
        })

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

        account = FinanceAccount.objects.filter(
            user=request.user,
            is_manual=True,
            kind=FinanceAccount.Kind.CREDIT_CARD,
            name__iexact=name,
        ).order_by("id").first()
        account_created = account is None
        if account is None:
            account = FinanceAccount(user=request.user, name=name, kind=FinanceAccount.Kind.CREDIT_CARD, is_manual=True)
        account.name = name
        account.official_name = str(request.data.get("official_name") or "")
        account.current_balance = balance
        account.credit_limit = credit_limit
        account.metadata = {**(account.metadata or {}), **metadata}
        account.save()

        liability = FinanceLiability.objects.filter(
            user=request.user,
            is_manual=True,
            kind=FinanceLiability.Kind.CREDIT_CARD,
            account=account,
        ).order_by("id").first()
        if liability is None:
            liability = FinanceLiability.objects.filter(
                user=request.user,
                is_manual=True,
                kind=FinanceLiability.Kind.CREDIT_CARD,
                name__iexact=name,
                account__isnull=True,
            ).order_by("id").first()
        liability_created = liability is None
        if liability is None:
            liability = FinanceLiability(
                user=request.user,
                account=account,
                name=name,
                kind=FinanceLiability.Kind.CREDIT_CARD,
                is_manual=True,
            )
        else:
            liability.account = account
        liability.name = name
        liability.lender = str(request.data.get("lender") or "")
        liability.outstanding_balance = balance
        liability.minimum_payment = minimum
        liability.next_payment_amount = minimum
        liability.next_payment_date = due_date
        liability.apr = apr
        liability.metadata = {
            **(liability.metadata or {}),
            **metadata,
            "credit_limit": str(credit_limit) if credit_limit is not None else None,
        }
        liability.save()

        return Response(
            {
                "account": FinanceAccountSerializer(account).data,
                "liability": FinanceLiabilitySerializer(liability).data,
                "created": bool(account_created or liability_created),
            },
            status=status.HTTP_201_CREATED if (account_created or liability_created) else status.HTTP_200_OK,
        )
