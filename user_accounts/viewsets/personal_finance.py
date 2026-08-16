from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models.personal_finance import (
    FinanceAccount,
    FinanceBudget,
    FinanceConnection,
    FinanceGoal,
    FinanceLiability,
    FinanceObligation,
    FinanceTransaction,
)
from user_accounts.serializers.personal_finance import (
    FinanceAccountSerializer,
    FinanceBudgetSerializer,
    FinanceConnectionSerializer,
    FinanceGoalSerializer,
    FinanceLiabilitySerializer,
    FinanceObligationSerializer,
    FinanceTransactionSerializer,
)
from user_accounts.services.plaid_finance import create_link_token, exchange_public_token, sync_connection


class UserScopedModelViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class FinanceAccountViewSet(UserScopedModelViewSet):
    queryset = FinanceAccount.objects.all()
    serializer_class = FinanceAccountSerializer


class FinanceLiabilityViewSet(UserScopedModelViewSet):
    queryset = FinanceLiability.objects.all()
    serializer_class = FinanceLiabilitySerializer


class FinanceObligationViewSet(UserScopedModelViewSet):
    queryset = FinanceObligation.objects.all()
    serializer_class = FinanceObligationSerializer


class FinanceTransactionViewSet(UserScopedModelViewSet):
    queryset = FinanceTransaction.objects.select_related("account").all()
    serializer_class = FinanceTransactionSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        start = self.request.query_params.get("start")
        end = self.request.query_params.get("end")
        category = self.request.query_params.get("category")
        if start:
            qs = qs.filter(date__gte=start)
        if end:
            qs = qs.filter(date__lte=end)
        if category:
            qs = qs.filter(category_primary=category)
        return qs


class FinanceGoalViewSet(UserScopedModelViewSet):
    queryset = FinanceGoal.objects.all()
    serializer_class = FinanceGoalSerializer


class FinanceBudgetViewSet(UserScopedModelViewSet):
    queryset = FinanceBudget.objects.all()
    serializer_class = FinanceBudgetSerializer


class FinanceConnectionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = FinanceConnectionSerializer

    def get_queryset(self):
        return FinanceConnection.objects.filter(user=self.request.user)

    @action(detail=False, methods=["post"], url_path="plaid/link-token")
    def plaid_link_token(self, request):
        try:
            return Response(create_link_token(request.user), status=status.HTTP_200_OK)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    @action(detail=False, methods=["post"], url_path="plaid/exchange")
    def plaid_exchange(self, request):
        public_token = request.data.get("public_token")
        if not public_token:
            return Response({"detail": "public_token is required."}, status=status.HTTP_400_BAD_REQUEST)
        institution = request.data.get("institution") or {}
        try:
            connection = exchange_public_token(request.user, public_token, institution=institution)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(FinanceConnectionSerializer(connection).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="sync")
    def sync(self, request, pk=None):
        connection = self.get_object()
        try:
            sync_connection(connection)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(FinanceConnectionSerializer(connection).data)


class FinanceDashboardViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        user = request.user
        today = timezone.localdate()
        month_start = today.replace(day=1)
        next_30 = today + timedelta(days=30)

        accounts = FinanceAccount.objects.filter(user=user, is_hidden=False)
        liabilities = FinanceLiability.objects.filter(user=user)
        obligations = FinanceObligation.objects.filter(user=user, active=True)
        tx = FinanceTransaction.objects.filter(user=user, date__gte=month_start, date__lte=today)

        cash = accounts.filter(kind__in=[FinanceAccount.Kind.CHECKING, FinanceAccount.Kind.SAVINGS]).aggregate(v=Sum("current_balance"))["v"] or Decimal("0")
        debt = liabilities.aggregate(v=Sum("outstanding_balance"))["v"] or Decimal("0")
        credit_limit = accounts.filter(kind=FinanceAccount.Kind.CREDIT_CARD).aggregate(v=Sum("credit_limit"))["v"] or Decimal("0")
        credit_balance = accounts.filter(kind=FinanceAccount.Kind.CREDIT_CARD).aggregate(v=Sum("current_balance"))["v"] or Decimal("0")
        utilization = float((credit_balance / credit_limit) * 100) if credit_limit else None
        spend = tx.filter(amount__gt=0, is_transfer=False).aggregate(v=Sum("amount"))["v"] or Decimal("0")
        income_raw = tx.filter(amount__lt=0, is_transfer=False).aggregate(v=Sum("amount"))["v"] or Decimal("0")
        income = abs(income_raw)
        due = obligations.filter(next_due_date__gte=today, next_due_date__lte=next_30)
        due_total = due.aggregate(v=Sum("expected_amount"))["v"] or Decimal("0")
        liability_due = liabilities.filter(next_payment_date__gte=today, next_payment_date__lte=next_30)
        liability_due_total = liability_due.aggregate(v=Sum("next_payment_amount"))["v"] or Decimal("0")
        category_rows = tx.filter(amount__gt=0, is_transfer=False).values("category_primary").annotate(total=Sum("amount")).order_by("-total")[:8]
        connections = FinanceConnection.objects.filter(user=user)
        last_synced = connections.exclude(last_synced_at=None).order_by("-last_synced_at").values_list("last_synced_at", flat=True).first()

        return Response({
            "as_of": today,
            "last_synced_at": last_synced,
            "connections": FinanceConnectionSerializer(connections, many=True).data,
            "net_position": {"cash": cash, "debt": debt, "estimated_net_cash_less_debt": cash - debt},
            "credit": {"balance": credit_balance, "limit": credit_limit, "utilization_percent": round(utilization, 1) if utilization is not None else None},
            "this_month": {"income": income, "spending": spend, "cash_flow": income - spend},
            "next_30_days": {
                "bills_due": due_total,
                "debt_payments_due": liability_due_total,
                "total_due": due_total + liability_due_total,
                "obligations": FinanceObligationSerializer(due.order_by("next_due_date"), many=True).data,
                "liabilities": FinanceLiabilitySerializer(liability_due.order_by("next_payment_date"), many=True).data,
            },
            "spending_by_category": list(category_rows),
            "accounts": FinanceAccountSerializer(accounts, many=True).data,
            "liabilities": FinanceLiabilitySerializer(liabilities, many=True).data,
            "goals": FinanceGoalSerializer(FinanceGoal.objects.filter(user=user, active=True), many=True).data,
            "budgets": FinanceBudgetSerializer(FinanceBudget.objects.filter(user=user, active=True), many=True).data,
        })
