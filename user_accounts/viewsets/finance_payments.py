from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models.finance_payments import FinanceDebtPayment
from user_accounts.serializers.finance_payments import FinanceDebtPaymentSerializer
from user_accounts.serializers.personal_finance import FinanceLiabilitySerializer
from user_accounts.services.finance_payments import record_manual_debt_payment


class FinanceDebtPaymentViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = FinanceDebtPaymentSerializer

    def get_queryset(self):
        qs = FinanceDebtPayment.objects.filter(user=self.request.user).select_related("liability", "account", "funding_account")
        liability_id = self.request.query_params.get("liability")
        if liability_id:
            qs = qs.filter(liability_id=liability_id)
        return qs

    def create(self, request, *args, **kwargs):
        try:
            liability_id = int(request.data.get("liability"))
        except (TypeError, ValueError):
            return Response({"detail": "Choose a debt account."}, status=status.HTTP_400_BAD_REQUEST)

        funding_account_id = request.data.get("funding_account")
        if funding_account_id in (None, ""):
            funding_account_id = None
        else:
            try:
                funding_account_id = int(funding_account_id)
            except (TypeError, ValueError):
                return Response({"detail": "Choose a valid funding account."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payment = record_manual_debt_payment(
                user=request.user,
                liability_id=liability_id,
                amount=request.data.get("amount"),
                payment_date=request.data.get("payment_date"),
                notes=request.data.get("notes") or "",
                funding_account_id=funding_account_id,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        payment.refresh_from_db()
        payment.liability.refresh_from_db()
        return Response(
            {
                "payment": FinanceDebtPaymentSerializer(payment).data,
                "liability": FinanceLiabilitySerializer(payment.liability).data,
            },
            status=status.HTTP_201_CREATED,
        )
