from datetime import date
from django.test import SimpleTestCase, TestCase
from django.contrib.auth import get_user_model
from user_accounts.models import Business, CashFeeInvoice
from user_accounts.models.platform_billing import PlatformBillingProfile
from user_accounts.services.cash_fee_policy import cash_lock_date, should_lock_cash_fees
from user_accounts.services.cash_fee_locks import enforce_overdue_cash_fee_locks
from user_accounts.services.cash_fee_unlock import unlock_settled_cash_fees
from user_accounts.services.marketplace_payment_policy import proposed_marketplace_quote

class PriceMathTests(SimpleTestCase):
    def test_fee_and_calendar_cap(self):
        self.assertEqual(cash_lock_date(date(2026,1,31)),date(2026,4,30))
        self.assertFalse(should_lock_cash_fees(date(2026,7,1),date(2026,9,30)))
        self.assertTrue(should_lock_cash_fees(date(2026,7,1),date(2026,10,1)))
        self.assertEqual(proposed_marketplace_quote("10000.00").customer_platform_fee,50)

class CashFeeLockTests(TestCase):
    def test_wait_three_months_then_unlock(self):
        owner=get_user_model().objects.create_user(username="cash_tester",email="cash@example.com",password="StrongPassword123!")
        business=Business.objects.create(name="Pilot Electric",owner=owner)
        inv=CashFeeInvoice.objects.create(business=business,amount_cents=1000,due_date=date(2026,8,1),
            period_start=date(2026,6,1),period_end=date(2026,6,30))
        today=date(2026,10,29)
        self.assertEqual(enforce_overdue_cash_fee_locks(today=today).businesses_locked,0)
        inv.due_date=date(2026,7,1)
        inv.save(update_fields=["due_date"])
        self.assertEqual(enforce_overdue_cash_fee_locks(today=today).businesses_locked,1)
        self.assertTrue(PlatformBillingProfile.objects.get(business=business).is_locked)
        inv.status=CashFeeInvoice.Status.PAID
        inv.save(update_fields=["status"])
        self.assertEqual(unlock_settled_cash_fees(today=today),1)
        self.assertFalse(PlatformBillingProfile.objects.get(business=business).is_locked)
