from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from user_accounts.models import Business, Invoice, Ticket
from .models import BusinessExpense
from .views import (
    CashForecastAPIView, ExpenseDetailAPIView, ExpenseListCreateAPIView,
    FinanceSettingsAPIView, FinanceSummaryAPIView, JobCostReviewAPIView, JobProfitAPIView,
)


class BusinessFinanceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="finance-owner", password="unused")
        self.stranger = user_model.objects.create_user(username="finance-stranger", password="unused")
        self.business = Business.objects.create(name="Primary Co", owner=self.owner)
        self.other = Business.objects.create(name="Other Co", owner=self.stranger)
        self.ticket = Ticket.objects.create(customer=self.owner, assigned_business=self.business, status=Ticket.Status.PAID)
        self.other_ticket = Ticket.objects.create(customer=self.stranger, assigned_business=self.other)
        self.factory = APIRequestFactory()

    def call(self, view, method, route, user=None, business=None, data=None, kwargs=None):
        fn = getattr(self.factory, method.lower())
        request = fn(route, data or {}, format="json", HTTP_X_BUSINESS_ID=str((business or self.business).id))
        force_authenticate(request, user or self.owner)
        return view.as_view()(request, **(kwargs or {}))

    def test_forbids_cross_business_finance_access(self):
        response = self.call(ExpenseListCreateAPIView, "get", "/api/v1/business-finance/expenses/", user=self.stranger)
        self.assertEqual(response.status_code, 403)
        response = self.call(ExpenseListCreateAPIView, "post", "/api/v1/business-finance/expenses/", data={
            "ticket": self.other_ticket.id, "description": "Cross tenant",
            "category": "LABOR", "quantity": "2", "unit_cost": "30",
        })
        self.assertEqual(response.status_code, 400)

    def test_expense_amount_verified_job_cost_and_recheck(self):
        self.assertEqual(self.call(ExpenseListCreateAPIView, "post", "/expenses/", data={
            "ticket": self.ticket.id, "description": "Two labor hours",
            "category": "LABOR", "quantity": "2.0", "unit_cost": "55.00",
            "status": "PAID",
        }).status_code, 201)
        item = BusinessExpense.objects.get(business=self.business)
        self.assertEqual(item.amount, Decimal("110.00"))
        self.assertIsNotNone(item.paid_on)

        paid_at = timezone.now()
        Invoice.objects.create(
            ticket=self.ticket, status=Invoice.Status.PAID, paid_at=paid_at,
            total=Decimal("250.00"), amount_paid=Decimal("250.00"),
        )
        initial = self.call(JobProfitAPIView, "get", "/job-profit/?ticket=%s" % self.ticket.id)
        self.assertFalse(initial.data[0]["verified"])

        review = self.call(JobCostReviewAPIView, "patch", "/jobs/%s/review/" % self.ticket.id,
            data={"costs_complete": True}, kwargs={"ticket_id": self.ticket.id})
        self.assertEqual(review.status_code, 200)
        checked = self.call(JobProfitAPIView, "get", "/job-profit/")
        self.assertEqual(checked.data[0]["contribution"], "140.00")
        self.assertEqual(checked.data[0]["margin_percent"], 56.0)

        response = self.call(ExpenseDetailAPIView, "patch", "/expenses/%s/" % item.id,
            data={"unit_cost": "65.00"}, kwargs={"expense_id": item.id})
        self.assertEqual(response.status_code, 200)
        latest = self.call(JobProfitAPIView, "get", "/job-profit/")
        self.assertFalse(latest.data[0]["verified"])

    def test_month_summary_and_cash_scenario(self):
        today = timezone.localdate()
        Invoice.objects.create(ticket=self.ticket, status=Invoice.Status.PAID,
            total=Decimal("300.00"), amount_paid=Decimal("300.00"), paid_at=timezone.now())
        exp = self.call(ExpenseListCreateAPIView, "post", "/expenses/", data={
            "description": "Monthly tools", "category": "OVERHEAD",
            "quantity": "1", "unit_cost": "80", "status": "PAID",
            "incurred_on": today.isoformat(),
        })
        self.assertEqual(exp.status_code, 201)
        summary = self.call(FinanceSummaryAPIView, "get", "/summary/?month=" + today.strftime("%Y-%m"))
        self.assertEqual(summary.data["revenue"], "300.00")
        self.assertEqual(summary.data["costs"], "80.00")
        self.assertEqual(summary.data["recorded_contribution"], "220.00")
        self.assertEqual(summary.data["profit_status"], "PROVISIONAL")

        settings = self.call(FinanceSettingsAPIView, "patch", "/settings/", data={
            "opening_cash_balance": "1000.00",
            "opening_cash_date": (today - timedelta(days=1)).isoformat(),
        })
        self.assertEqual(settings.status_code, 200)
        scenario = self.call(CashForecastAPIView, "get", "/cash-forecast/?days=30")
        self.assertEqual(scenario.data["estimated_cash_today"], "1220.00")

    def test_paid_invoice_does_not_double_count_confirmed_cash(self):
        self.ticket.payment_method = Ticket.PaymentMethod.CASH
        self.ticket.cash_confirmed_at = timezone.now()
        self.ticket.total_amount_cents = 50000
        self.ticket.save()
        Invoice.objects.create(ticket=self.ticket, status=Invoice.Status.PAID,
            total=Decimal("500.00"), amount_paid=Decimal("500.00"), paid_at=timezone.now())
        summary = self.call(FinanceSummaryAPIView, "get", "/summary/")
        self.assertEqual(summary.data["revenue"], "500.00")
        self.assertEqual(summary.data["confirmed_cash_tickets"], 0)
