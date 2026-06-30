from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from user_accounts.models import AutomationRule, Business, BusinessMember, ServiceCategory, Ticket, TicketMessage

EMAILS={"customer":"demo.customer@syncworks.app","owner":"demo.owner@syncworks.app","dispatch":"demo.dispatch@syncworks.app","tech1":"demo.tech1@syncworks.app","tech2":"demo.tech2@syncworks.app"}
BUSINESS_NAME="SyncWorks Demo Services"
CATEGORY_KEY="syncworks-demo-hvac"
PASSWORD="SyncWorksDemo!2026"

def fields(model): return {f.name for f in model._meta.get_fields()}
def apply(obj,**values):
    changed=[]; allowed=fields(type(obj))
    for key,value in values.items():
        if key in allowed:setattr(obj,key,value);changed.append(key)
    if changed:obj.save(update_fields=changed)

class Command(BaseCommand):
    help="Create or reset an isolated SyncWorks demo workspace."
    def add_arguments(self,parser):parser.add_argument("--reset",action="store_true")
    @transaction.atomic
    def handle(self,*args,**opts):
        if opts["reset"]:self.reset_demo()
        users=self.make_users();biz=self.make_business(users);cat=self.make_category();tickets=self.make_tickets(users,biz,cat);rules=self.make_rules(biz)
        self.stdout.write(self.style.SUCCESS("SyncWorks demo workspace is ready."))
        self.stdout.write(f"Business: {biz.name} (ID {biz.id})")
        self.stdout.write(f"Customer: {EMAILS['customer']}")
        self.stdout.write(f"Owner: {EMAILS['owner']}")
        self.stdout.write(f"Dispatcher: {EMAILS['dispatch']}")
        self.stdout.write(f"Technicians: {EMAILS['tech1']}, {EMAILS['tech2']}")
        self.stdout.write(f"Password: {PASSWORD}")
        self.stdout.write(f"Tickets: {len(tickets)} | Automation rules: {len(rules)}")
        self.stdout.write(self.style.WARNING("Demo-only identities created. God Mode and real users were not modified."))
    def reset_demo(self):
        User=get_user_model();users=User.objects.filter(email__in=EMAILS.values());businesses=Business.objects.filter(name=BUSINESS_NAME)
        Ticket.objects.filter(assigned_business__in=businesses).delete();Ticket.objects.filter(customer__in=users).delete();businesses.delete();ServiceCategory.objects.filter(key=CATEGORY_KEY).delete();users.delete()
        self.stdout.write("Removed prior demo-only records.")
    def make_users(self):
        User=get_user_model();allowed=fields(User);names={"customer":("Demo","Customer"),"owner":("Olivia","Owner"),"dispatch":("Dana","Dispatcher"),"tech1":("Marcus","Technician"),"tech2":("Taylor","Technician")};out={}
        for key,email in EMAILS.items():
            defaults={k:v for k,v in {"username":email,"first_name":names[key][0],"last_name":names[key][1],"is_active":True}.items() if k in allowed}
            lookup={"email":email} if "email" in allowed else {"username":email};user,_=User.objects.get_or_create(**lookup,defaults=defaults)
            for attr,value in defaults.items():setattr(user,attr,value)
            if "role" in allowed:user.role="CUSTOMER" if key=="customer" else("SBO" if key=="owner" else "EMPLOYEE")
            user.set_password(PASSWORD);user.save();out[key]=user
        return out
    def make_business(self,users):
        biz,_=Business.objects.get_or_create(name=BUSINESS_NAME,defaults={"owner":users["owner"]})
        apply(biz,owner=users["owner"],is_active=True,is_demo=True,exclude_from_kpis=True,billing_exempt=True,billing_exempt_reason="SyncWorks live demo sandbox",subscriptions_exempt=True,subscriptions_exempt_reason="SyncWorks live demo sandbox",base_zip="36104",accepts_marketplace_tickets=True,business_email=EMAILS["owner"],city="Montgomery",state="AL")
        specs=[("owner","OWNER",1,1,1),("dispatch","DISPATCH",1,1,0),("tech1","TECHNICIAN",0,0,1),("tech2","TECHNICIAN",0,0,1)]
        allowed=fields(BusinessMember)
        for key,role,schedule,assign,close in specs:
            defaults={"role":role};
            if "is_active" in allowed:defaults["is_active"]=True
            member,_=BusinessMember.objects.get_or_create(business=biz,user=users[key],defaults=defaults)
            apply(member,role=role,is_active=True,can_manage_schedule=bool(schedule),can_assign_tickets=bool(assign),can_close_tickets=bool(close),can_manage_invoices=key in {"owner","dispatch"})
        return biz
    def make_category(self):
        cat,_=ServiceCategory.objects.get_or_create(key=CATEGORY_KEY,defaults={"name":"HVAC Repair"});apply(cat,name="HVAC Repair",is_active=True);return cat
    def make_tickets(self,users,biz,cat):
        now=timezone.now();specs=[("NEW",None,"New marketplace request"),("ACCEPTED",users["dispatch"],"Accepted"),("SCHEDULED",users["tech1"],"Scheduled"),("EN_ROUTE",users["tech1"],"En route"),("ON_SITE",users["tech2"],"On site"),("IN_PROGRESS",users["tech2"],"In progress"),("COMPLETED",users["tech1"],"Completed"),("INVOICED",users["tech1"],"Invoice due")];out=[]
        for i,(status,member,label) in enumerate(specs,1):
            marker=f"[SYNCWORKS DEMO {i}]";ticket=Ticket.objects.filter(customer=users["customer"],assigned_business=biz,service_address__contains=marker).first()
            if not ticket:ticket=Ticket.objects.create(customer=users["customer"],assigned_business=biz,category=cat,status=status,service_zip="36104",service_address=f"100 Demo Commerce St {marker}")
            apply(ticket,status=status,assigned_member=member,is_marketplace=status=="NEW",service_zip="36104",service_address=f"100 Demo Commerce St {marker}",scheduled_at=now+timedelta(days=i,hours=9))
            if not TicketMessage.objects.filter(ticket=ticket,body__startswith="[DEMO]").exists():TicketMessage.objects.create(ticket=ticket,sender=users["owner"],body=f"[DEMO] HVAC repair â€” {label}",type=TicketMessage.MessageType.SYSTEM)
            out.append(ticket)
        return out
    def make_rules(self,biz):
        specs=[("Demo: accepted follow-up","TICKET_STATUS",{"status":"ACCEPTED"},"CREATE_REQUIREMENT",{"title":"Confirm schedule with customer"}),("Demo: completed invoice reminder","TICKET_STATUS",{"status":"COMPLETED"},"CREATE_REQUIREMENT",{"title":"Prepare and send invoice"}),("Demo: delayed ETA alert","ETA_DELAYED",{"status":"DELAYED"},"CREATE_ALERT",{"title":"Technician arrival delayed"})];out=[]
        for priority,(name,trigger,trigger_config,action,action_config) in enumerate(specs,10):
            rule,_=AutomationRule.objects.update_or_create(business=biz,name=name,defaults={"trigger_type":trigger,"trigger_config":trigger_config,"action_type":action,"action_config":action_config,"priority":priority,"is_active":True});out.append(rule)
        return out
