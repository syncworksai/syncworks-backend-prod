from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from user_accounts.models import Invoice, Ticket
from user_accounts.viewsets.ticket_conversations import _business_context
from .models import BusinessExpense, BusinessFinanceSettings, CashForecastItem, JobCostReview
from .serializers import ExpenseSerializer, CashForecastSerializer, FinanceSettingsSerializer

ZERO = Decimal("0.00")
ACTUAL_COST_STATUSES = (BusinessExpense.Status.INCURRED, BusinessExpense.Status.PAID)


def finance_business(request):
    business, member, _oversight = _business_context(request)
    user = request.user
    allowed = (
        user.is_superuser
        or bool(getattr(user, "is_platform_admin", False))
        or business.owner_id == user.id
        or (member is not None and str(member.role or "").upper() in {"OWNER", "MANAGER", "ACCOUNTING", "ADMIN"})
    )
    if not allowed:
        raise PermissionDenied("Finance access requires business owner, manager, or accounting permissions.")
    return business


def as_money(value):
    return str(Decimal(value or ZERO).quantize(Decimal("0.01")))


def invalidate_reconciliation(business, *dates):
    """Any corrected cost reopens affected and later months."""
    instance = BusinessFinanceSettings.objects.filter(business=business).first()
    if not instance or not instance.expenses_reconciled_through:
        return
    affected = [d for d in dates if d and d <= instance.expenses_reconciled_through]
    if not affected:
        return
    first = min(affected).replace(day=1)
    instance.expenses_reconciled_through = first - timedelta(days=1)
    instance.save(update_fields=["expenses_reconciled_through", "updated_at"])


def expense_rows(business):
    return BusinessExpense.objects.filter(business=business).select_related("ticket")


def invoice_paid_amount(invoice):
    amount = Decimal(invoice.amount_paid or ZERO)
    return amount if amount > ZERO else Decimal(invoice.total or ZERO)


def paid_invoice_rows(business):
    return Invoice.objects.filter(
        ticket__assigned_business=business,
        status=Invoice.Status.PAID,
        paid_at__isnull=False,
    )


def verified_cash_tickets(business):
    invoiced_ticket_ids = Invoice.objects.filter(
        ticket__assigned_business=business,
        status=Invoice.Status.PAID,
    ).values_list("ticket_id", flat=True)
    return Ticket.objects.filter(
        assigned_business=business,
        payment_method=Ticket.PaymentMethod.CASH,
        cash_confirmed_at__isnull=False,
    ).exclude(id__in=invoiced_ticket_ids)


def revenue_between(business, start, finish):
    invoices = paid_invoice_rows(business).filter(paid_at__date__gte=start, paid_at__date__lte=finish)
    invoice_total = sum((invoice_paid_amount(invoice) for invoice in invoices), ZERO)
    cash = verified_cash_tickets(business).filter(cash_confirmed_at__date__gte=start, cash_confirmed_at__date__lte=finish)
    cash_total = sum((Decimal(ticket.total_amount_cents or 0) / Decimal("100") for ticket in cash), ZERO)
    return invoice_total + cash_total, invoices.count(), cash.count()


def parse_month(value):
    today = timezone.localdate()
    if not value:
        return today.replace(day=1)
    try:
        parsed = date.fromisoformat(value + "-01")
    except (ValueError, TypeError):
        raise ValidationError({"month": "Use YYYY-MM."})
    return parsed


def date_period(month):
    return month, month.replace(day=monthrange(month.year, month.month)[1])


def cost_breakdown(business, ticket=None, start=None, finish=None):
    qs = expense_rows(business).filter(status__in=ACTUAL_COST_STATUSES)
    if ticket is not None:
        qs = qs.filter(ticket=ticket)
    if start:
        qs = qs.filter(incurred_on__gte=start)
    if finish:
        qs = qs.filter(incurred_on__lte=finish)
    totals = {category: ZERO for category in BusinessExpense.Category.values}
    for row in qs.values("category").annotate(total=Sum("amount")):
        totals[row["category"]] = row["total"] or ZERO
    return totals


def job_revenue(business, ticket):
    invoices = list(paid_invoice_rows(business).filter(ticket=ticket))
    billed = sum((invoice_paid_amount(invoice) for invoice in invoices), ZERO)
    if invoices:
        return billed, "PAID_INVOICE"
    if (
        ticket.payment_method == Ticket.PaymentMethod.CASH
        and ticket.cash_confirmed_at
    ):
        return Decimal(ticket.total_amount_cents or 0) / Decimal("100"), "CONFIRMED_CASH"
    return None, "NO_CONFIRMED_COLLECTION"


class ExpenseListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business = finance_business(request)
        qs = expense_rows(business)
        if request.query_params.get("ticket"):
            qs = qs.filter(ticket_id=request.query_params["ticket"])
        if request.query_params.get("month"):
            start, finish = date_period(parse_month(request.query_params["month"]))
            qs = qs.filter(incurred_on__range=(start, finish))
        return Response(ExpenseSerializer(qs[:500], many=True, context={"business": business}).data)

    def post(self, request):
        business = finance_business(request)
        serializer = ExpenseSerializer(data=request.data, context={"business": business})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            instance = serializer.save(business=business, created_by=request.user)
            invalidate_reconciliation(business, instance.incurred_on)
            if instance.ticket_id:
                JobCostReview.objects.filter(ticket_id=instance.ticket_id, business=business).update(
                    costs_complete=False, reviewed_by=None, reviewed_at=None
                )
        return Response(ExpenseSerializer(instance, context={"business": business}).data, status=201)


class ExpenseDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, expense_id):
        business = finance_business(request)
        expense = expense_rows(business).filter(pk=expense_id).first()
        if expense is None:
            raise Http404
        serializer = ExpenseSerializer(expense, data=request.data, partial=True, context={"business": business})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            original_ticket_id = expense.ticket_id
            original_incurred_on = expense.incurred_on
            instance = serializer.save()
            invalidate_reconciliation(business, original_incurred_on, instance.incurred_on)
            review_ids = [tid for tid in {original_ticket_id, instance.ticket_id} if tid]
            JobCostReview.objects.filter(ticket_id__in=review_ids, business=business).update(
                costs_complete=False, reviewed_by=None, reviewed_at=None
            )
        return Response(ExpenseSerializer(instance, context={"business": business}).data)


class ForecastItemListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business = finance_business(request)
        return Response(CashForecastSerializer(CashForecastItem.objects.filter(business=business)[:500], many=True).data)

    def post(self, request):
        business = finance_business(request)
        serializer = CashForecastSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(business=business, created_by=request.user)
        return Response(CashForecastSerializer(instance).data, status=201)


class ForecastItemDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, forecast_id):
        business = finance_business(request)
        entry = CashForecastItem.objects.filter(business=business, pk=forecast_id).first()
        if entry is None:
            raise Http404
        serializer = CashForecastSerializer(entry, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(CashForecastSerializer(serializer.save()).data)


class FinanceSettingsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business = finance_business(request)
        instance = BusinessFinanceSettings.objects.filter(business=business).first()
        return Response(FinanceSettingsSerializer(instance).data if instance else {
            "opening_cash_balance": None, "opening_cash_date": None, "expenses_reconciled_through": None,
        })

    def patch(self, request):
        business = finance_business(request)
        instance, _ = BusinessFinanceSettings.objects.get_or_create(business=business)
        serializer = FinanceSettingsSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(FinanceSettingsSerializer(serializer.save(updated_by=request.user)).data)


class JobProfitAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business = finance_business(request)
        qs = Ticket.objects.filter(assigned_business=business).order_by("-created_at")
        if request.query_params.get("ticket"):
            qs = qs.filter(pk=request.query_params["ticket"])
        rows = []
        for ticket in qs[:100]:
            revenue, source = job_revenue(business, ticket)
            by_category = cost_breakdown(business, ticket=ticket)
            total_cost = sum(by_category.values(), ZERO)
            review = JobCostReview.objects.filter(business=business, ticket=ticket).first()
            complete = bool(review and review.costs_complete)
            verified = bool(complete and revenue is not None)
            contribution = revenue - total_cost if verified else None
            margin = (contribution / revenue * Decimal("100")) if verified and revenue > ZERO else None
            rows.append({
                "ticket": ticket.id,
                "title": ticket.work_title or f"Ticket #{ticket.id}",
                "status": ticket.status,
                "revenue": as_money(revenue) if revenue is not None else None,
                "revenue_source": source,
                "labor": as_money(by_category["LABOR"]),
                "materials": as_money(by_category["MATERIAL"]),
                "subcontractor": as_money(by_category["SUBCONTRACTOR"]),
                "other_cost": as_money(total_cost - by_category["LABOR"] - by_category["MATERIAL"] - by_category["SUBCONTRACTOR"]),
                "tracked_cost": as_money(total_cost),
                "costs_complete": complete,
                "verified": verified,
                "contribution": as_money(contribution) if contribution is not None else None,
                "margin_percent": round(float(margin), 1) if margin is not None else None,
            })
        return Response(rows)


class JobCostReviewAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, ticket_id):
        business = finance_business(request)
        ticket = Ticket.objects.filter(assigned_business=business, pk=ticket_id).first()
        if ticket is None:
            raise Http404
        complete = request.data.get("costs_complete")
        if not isinstance(complete, bool):
            raise ValidationError({"costs_complete": "Provide true or false."})
        with transaction.atomic():
            review, _ = JobCostReview.objects.update_or_create(
                business=business, ticket=ticket,
                defaults={
                    "costs_complete": complete,
                    "reviewed_at": timezone.now() if complete else None,
                    "reviewed_by": request.user if complete else None,
                },
            )
        return Response({"ticket": ticket.id, "costs_complete": review.costs_complete, "reviewed_at": review.reviewed_at})


class FinanceSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business = finance_business(request)
        start, finish = date_period(parse_month(request.query_params.get("month")))
        income, invoice_count, cash_count = revenue_between(business, start, finish)
        expenses = cost_breakdown(business, start=start, finish=finish)
        costs = sum(expenses.values(), ZERO)
        contribution = income - costs
        settings = BusinessFinanceSettings.objects.filter(business=business).first()
        reconciled = bool(settings and settings.expenses_reconciled_through and settings.expenses_reconciled_through >= finish)
        by_category = {key: as_money(value) for key, value in expenses.items()}
        period_paid = expense_rows(business).filter(status=BusinessExpense.Status.PAID, paid_on__range=(start, finish))
        cash_out = period_paid.aggregate(amount=Sum("amount"))["amount"] or ZERO
        upcoming_due = expense_rows(business).filter(
            status__in=[BusinessExpense.Status.PLANNED, BusinessExpense.Status.INCURRED],
            due_on__isnull=False, due_on__lte=timezone.localdate(),
        ).aggregate(amount=Sum("amount"))["amount"] or ZERO
        return Response({
            "month": start.strftime("%Y-%m"),
            "basis": "Collected invoices and confirmed cash, less recorded costs incurred in the month",
            "reconciled": reconciled,
            "revenue": as_money(income),
            "paid_invoices": invoice_count,
            "confirmed_cash_tickets": cash_count,
            "costs": as_money(costs),
            "cost_breakdown": by_category,
            "recorded_contribution": as_money(contribution),
            "recorded_margin_percent": round(float(contribution / income * Decimal("100")), 1) if income > ZERO else None,
            "cash_expenses_paid": as_money(cash_out),
            "overdue_expenses": as_money(upcoming_due),
            "profit_status": "OWNER_RECONCILED" if reconciled else "PROVISIONAL",
            "disclaimer": "Not an audited financial statement. Revenue is collected-basis while expense costs are incurred-basis; reconcile all transactions before treating margin as final.",
        })


class CashForecastAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        business = finance_business(request)
        today = timezone.localdate()
        days = request.query_params.get("days") or "90"
        try:
            days = int(days)
        except ValueError:
            raise ValidationError({"days": "Use 30, 60, or 90."})
        if days not in (30, 60, 90):
            raise ValidationError({"days": "Use 30, 60, or 90."})
        until = today + timedelta(days=days)
        settings = BusinessFinanceSettings.objects.filter(business=business).first()
        starting_cash = None
        if settings and settings.opening_cash_balance is not None and settings.opening_cash_date:
            opening_date = settings.opening_cash_date
            if opening_date <= today:
                paid_income, _, _ = revenue_between(business, opening_date + timedelta(days=1), today)
                paid_expenses = expense_rows(business).filter(
                    status=BusinessExpense.Status.PAID, paid_on__gt=opening_date, paid_on__lte=today
                ).aggregate(total=Sum("amount"))["total"] or ZERO
                starting_cash = settings.opening_cash_balance + paid_income - paid_expenses

        events = []
        for item in CashForecastItem.objects.filter(business=business, status=CashForecastItem.Status.PLANNED, expected_on__lte=until):
            day = max(today, item.expected_on)
            events.append({
                "day": day, "description": item.description, "source": "MANUAL_PLAN",
                "direction": item.direction, "amount": item.amount,
            })
        for expense in expense_rows(business).filter(
            status__in=[BusinessExpense.Status.PLANNED, BusinessExpense.Status.INCURRED],
            due_on__isnull=False, due_on__lte=until,
        ):
            events.append({
                "day": max(today, expense.due_on),
                "description": expense.description, "source": "UNPAID_EXPENSE",
                "direction": "OUT", "amount": expense.amount,
            })
        events.sort(key=lambda item: (item["day"], item["direction"], item["description"]))
        balance = starting_cash
        checkpoints = {}
        row_items = []
        for offset in range(days + 1):
            current_date = today + timedelta(days=offset)
            for event in (e for e in events if e["day"] == current_date):
                if balance is not None:
                    balance += event["amount"] if event["direction"] == "IN" else -event["amount"]
                row_items.append({
                    "day": current_date.isoformat(), "description": event["description"],
                    "source": event["source"], "direction": event["direction"], "amount": as_money(event["amount"]),
                })
            if offset in (30, 60, 90):
                checkpoints[str(offset)] = as_money(balance) if balance is not None else None
        return Response({
            "days": days, "as_of": today.isoformat(),
            "opening_cash_balance": as_money(settings.opening_cash_balance) if settings and settings.opening_cash_balance is not None else None,
            "opening_cash_date": settings.opening_cash_date if settings else None,
            "estimated_cash_today": as_money(starting_cash) if starting_cash is not None else None,
            "projected_cash_end": as_money(balance) if balance is not None else None,
            "checkpoints": checkpoints,
            "events": row_items[:500],
            "event_count": len(row_items),
            "disclaimer": "Scenario based on entered opening cash, confirmed receipts/paid costs and known future entries. Unentered income, debt payments and costs are excluded. Avoid entering the same planned outflow twice.",
        })
