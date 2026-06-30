from io import StringIO
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from user_accounts.management.commands.seed_syncworks_demo import BUSINESS_NAME, EMAILS
from user_accounts.models import AutomationRule, Business, Ticket

class DemoWorkspaceTests(TestCase):
    def test_seed_creates_workspace(self):
        call_command("seed_syncworks_demo",stdout=StringIO());User=get_user_model();self.assertEqual(User.objects.filter(email__in=EMAILS.values()).count(),len(EMAILS));biz=Business.objects.get(name=BUSINESS_NAME);self.assertEqual(biz.owner.email,EMAILS["owner"]);self.assertGreaterEqual(Ticket.objects.filter(assigned_business=biz).count(),8);self.assertGreaterEqual(AutomationRule.objects.filter(business=biz).count(),3)
    def test_seed_is_idempotent(self):
        call_command("seed_syncworks_demo",stdout=StringIO());first=Ticket.objects.filter(assigned_business__name=BUSINESS_NAME).count();call_command("seed_syncworks_demo",stdout=StringIO());self.assertEqual(Business.objects.filter(name=BUSINESS_NAME).count(),1);self.assertEqual(Ticket.objects.filter(assigned_business__name=BUSINESS_NAME).count(),first)
    def test_reset_preserves_real_data(self):
        User=get_user_model();real=User.objects.create_user(username="real",email="real@example.com",password="safe");biz=Business.objects.create(owner=real,name="Real Business");call_command("seed_syncworks_demo",stdout=StringIO());call_command("seed_syncworks_demo","--reset",stdout=StringIO());self.assertTrue(User.objects.filter(id=real.id).exists());self.assertTrue(Business.objects.filter(id=biz.id).exists())
    def test_reset_rebuilds_demo(self):
        call_command("seed_syncworks_demo",stdout=StringIO());old=Business.objects.get(name=BUSINESS_NAME).id;call_command("seed_syncworks_demo","--reset",stdout=StringIO());new=Business.objects.get(name=BUSINESS_NAME);self.assertNotEqual(old,new.id);self.assertGreaterEqual(Ticket.objects.filter(assigned_business=new).count(),8)
