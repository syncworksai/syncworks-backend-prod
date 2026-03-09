from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token
from django.utils import timezone

from user_accounts.models import (
    User, Roles,
    CustomerProfile, SmallBusinessOwnerProfile,
    Business, BusinessCategory, ServiceCategory,
    Connection,
)
from user_accounts.services.tickets import create_request_and_ticket


class Command(BaseCommand):
    help = "Seed SyncWorks with platform owner, customer, SBO+business, accepted connection, and a ticket."

    def handle(self, *args, **kwargs):
        # Platform owner
        platform, _ = User.objects.get_or_create(email="platform@syncworks.test", defaults={"role": Roles.PLATFORM_OWNER, "is_staff": True})
        if not platform.has_usable_password():
            platform.set_password("Password123!")
            platform.save()

        # Customer
        customer, created = User.objects.get_or_create(email="customer@syncworks.test", defaults={"role": Roles.CUSTOMER})
        if created or not customer.has_usable_password():
            customer.set_password("Password123!")
            customer.save()
        CustomerProfile.objects.get_or_create(user=customer)

        # SBO
        sbo, created = User.objects.get_or_create(email="sbo@syncworks.test", defaults={"role": Roles.SBO})
        if created or not sbo.has_usable_password():
            sbo.set_password("Password123!")
            sbo.save()
        SmallBusinessOwnerProfile.objects.get_or_create(user=sbo, defaults={"business_name": "SBO Plumbing Co"})

        # Category
        cat, _ = ServiceCategory.objects.get_or_create(key="plumbing", defaults={"name": "Plumbing", "description": "Leaks and repairs"})

        # Business
        biz, _ = Business.objects.get_or_create(owner=sbo, name="SBO Plumbing Co", defaults={"is_active": True, "created_at": timezone.now()})
        BusinessCategory.objects.get_or_create(business=biz, category=cat)

        # Connection accepted
        conn, _ = Connection.objects.get_or_create(customer=customer, sbo_user=sbo, defaults={"status": Connection.Status.ACCEPTED})
        if conn.status != Connection.Status.ACCEPTED:
            conn.status = Connection.Status.ACCEPTED
            conn.save()

        # Ticket
        sr = create_request_and_ticket(customer=customer, category=cat, title="Seed: Fix faucet", description="Kitchen faucet leaking")
        ticket = sr.ticket

        def tok(u):
            t, _ = Token.objects.get_or_create(user=u)
            return t.key

        self.stdout.write("\n=== Seed Complete ===")
        self.stdout.write(f"Platform Owner: platform@syncworks.test  PASS=Password123!  TOKEN={tok(platform)}")
        self.stdout.write(f"Customer:       customer@syncworks.test  PASS=Password123!  TOKEN={tok(customer)}")
        self.stdout.write(f"SBO:            sbo@syncworks.test       PASS=Password123!  TOKEN={tok(sbo)}")
        self.stdout.write(f"Business ID: {biz.id}")
        self.stdout.write(f"Ticket ID: {ticket.id}")
