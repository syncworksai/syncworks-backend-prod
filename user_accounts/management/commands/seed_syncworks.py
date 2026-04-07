from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token
from django.utils import timezone

from user_accounts.models import (
    User,
    CustomerProfile,
    SmallBusinessOwnerProfile,
    Business,
    BusinessMember,
    ServiceCategory,
)
from user_accounts.services.tickets import create_request_and_ticket

try:
    from user_accounts.models.user import Roles
except Exception:
    class Roles:
        PLATFORM_OWNER = "PLATFORM_OWNER"
        CUSTOMER = "CUSTOMER"
        SBO = "SBO"


SEED_ZIP = "40509"


class Command(BaseCommand):
    help = "Seed SyncWorks with platform owner, customer, SBO+business, and a marketplace-ready ticket."

    def _upsert_user(self, *, email: str, role: str, is_staff: bool = False):
        email = (email or "").strip().lower()
        username = email

        user = User.objects.filter(email=email).first()
        if user is None:
            user = User.objects.filter(username=username).first()

        if user is None:
            user = User.objects.create(
                email=email,
                username=username,
                role=role,
                is_staff=is_staff,
            )
        else:
            changed = False

            if getattr(user, "email", "") != email:
                user.email = email
                changed = True

            if getattr(user, "username", "") != username:
                clash = User.objects.filter(username=username).exclude(id=user.id).exists()
                if clash:
                    raise RuntimeError(
                        f"Cannot assign username '{username}' because another user already owns it."
                    )
                user.username = username
                changed = True

            if getattr(user, "role", None) != role:
                user.role = role
                changed = True

            if bool(getattr(user, "is_staff", False)) != bool(is_staff):
                user.is_staff = bool(is_staff)
                changed = True

            if changed:
                user.save()

        user.set_password("Password123!")
        user.save()
        return user

    def _ensure_customer_profile(self, user):
        CustomerProfile.objects.get_or_create(user=user)

    def _ensure_sbo_profile(self, user):
        SmallBusinessOwnerProfile.objects.get_or_create(user=user)

    def _ensure_owner_membership(self, business, user):
        membership, created = BusinessMember.objects.get_or_create(
            business=business,
            user=user,
            defaults={"role": BusinessMember.ROLE_OWNER, "is_active": True},
        )

        changed = False

        if getattr(membership, "role", None) != BusinessMember.ROLE_OWNER:
            membership.role = BusinessMember.ROLE_OWNER
            changed = True

        if not bool(getattr(membership, "is_active", False)):
            membership.is_active = True
            changed = True

        if hasattr(membership, "apply_role_defaults"):
            membership.apply_role_defaults()
            changed = True

        if changed:
            membership.save()

        return membership

    def handle(self, *args, **kwargs):
        platform = self._upsert_user(
            email="platform@syncworks.test",
            role=Roles.PLATFORM_OWNER,
            is_staff=True,
        )

        customer = self._upsert_user(
            email="customer@syncworks.test",
            role=Roles.CUSTOMER,
            is_staff=False,
        )
        self._ensure_customer_profile(customer)

        sbo = self._upsert_user(
            email="sbo@syncworks.test",
            role=Roles.SBO,
            is_staff=False,
        )
        self._ensure_sbo_profile(sbo)

        cat = ServiceCategory.objects.filter(
            key="home-property-services--plumbing--fix-leaking-pipe"
        ).first()

        if not cat:
            self.stdout.write(
                self.style.ERROR(
                    "Missing seeded plumbing leaf category. Run: python manage.py seed_service_categories --reset"
                )
            )
            return

        biz, created = Business.objects.get_or_create(
            owner=sbo,
            name="SBO Plumbing Co",
            defaults={
                "is_active": True,
                "created_at": timezone.now(),
                "accepts_marketplace_tickets": True,
                "base_zip": SEED_ZIP,
                "service_radius_miles": 25,
                "business_email": "sbo@syncworks.test",
                "owner_name": "Seed SBO",
                "services_text": "Plumbing repairs and faucet/leak service.",
            },
        )

        biz_changed = False

        if not bool(getattr(biz, "is_active", False)):
            biz.is_active = True
            biz_changed = True

        if not bool(getattr(biz, "accepts_marketplace_tickets", False)):
            biz.accepts_marketplace_tickets = True
            biz_changed = True

        if (getattr(biz, "base_zip", "") or "").strip() != SEED_ZIP:
            biz.base_zip = SEED_ZIP
            biz_changed = True

        if int(getattr(biz, "service_radius_miles", 0) or 0) != 25:
            biz.service_radius_miles = 25
            biz_changed = True

        if hasattr(biz, "business_email") and (getattr(biz, "business_email", "") or "").strip() != "sbo@syncworks.test":
            biz.business_email = "sbo@syncworks.test"
            biz_changed = True

        if hasattr(biz, "owner_name") and not (getattr(biz, "owner_name", "") or "").strip():
            biz.owner_name = "Seed SBO"
            biz_changed = True

        if hasattr(biz, "services_text") and not (getattr(biz, "services_text", "") or "").strip():
            biz.services_text = "Plumbing repairs and faucet/leak service."
            biz_changed = True

        if biz_changed:
            biz.save()

        biz.services_offered.add(cat)
        self._ensure_owner_membership(biz, sbo)

        sr = create_request_and_ticket(
            customer=customer,
            category=cat,
            title="Seed: Fix faucet",
            description="Kitchen faucet leaking",
            service_zip=SEED_ZIP,
            service_address="123 Seed St",
            service_radius_miles=25,
            is_marketplace=True,
        )
        ticket = sr.ticket

        def tok(u):
            t, _ = Token.objects.get_or_create(user=u)
            return t.key

        self.stdout.write("\n=== Seed Complete ===")
        self.stdout.write(f"Platform Owner: platform@syncworks.test  PASS=Password123!  TOKEN={tok(platform)}")
        self.stdout.write(f"Customer:       customer@syncworks.test  PASS=Password123!  TOKEN={tok(customer)}")
        self.stdout.write(f"SBO:            sbo@syncworks.test       PASS=Password123!  TOKEN={tok(sbo)}")
        self.stdout.write(f"Business ID: {biz.id}")
        self.stdout.write(f"Category ID: {cat.id}")
        self.stdout.write(f"Category Key: {cat.key}")
        self.stdout.write(f"Business ZIP: {biz.base_zip}")
        self.stdout.write(f"Ticket ID: {ticket.id}")
        self.stdout.write(f"Ticket Marketplace: {ticket.is_marketplace}")
        self.stdout.write(f"Ticket ZIP: {ticket.service_zip}")