# backend/user_accounts/management/commands/why_ticket_ineligible.py
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from user_accounts.models import Business, Ticket
from user_accounts.services.tickets import is_ticket_eligible_for_business


class Command(BaseCommand):
    help = "Explain why a marketplace ticket is (in)eligible for a business."

    def add_arguments(self, parser):
        parser.add_argument("--ticket", type=int, required=True, help="Ticket ID")
        parser.add_argument("--business", type=int, required=True, help="Business ID")

    def handle(self, *args, **options):
        ticket_id = options["ticket"]
        business_id = options["business"]

        ticket = Ticket.objects.filter(id=ticket_id).select_related("service_request").first()
        if not ticket:
            raise CommandError(f"Ticket {ticket_id} not found")

        biz = Business.objects.filter(id=business_id).prefetch_related("services_offered").first()
        if not biz:
            raise CommandError(f"Business {business_id} not found")

        # Gather fields
        biz_active = bool(getattr(biz, "is_active", False))
        biz_accepts_marketplace = bool(getattr(biz, "accepts_marketplace_tickets", False))
        biz_base_zip = (getattr(biz, "base_zip", "") or "").strip()
        biz_radius = getattr(biz, "service_radius_miles", None)

        ticket_is_marketplace = bool(getattr(ticket, "is_marketplace", False))
        ticket_category_id = getattr(ticket, "category_id", None)

        ticket_zip = (getattr(ticket, "service_zip", "") or "").strip()
        sr_zip = ""
        try:
            sr = ticket.service_request
            sr_zip = (getattr(sr, "zip_code", "") or "").strip()
        except Exception:
            sr_zip = ""

        offered_ids = set(biz.services_offered.values_list("id", flat=True))

        # Official eligibility result
        eligible = is_ticket_eligible_for_business(ticket, biz)

        # Manual reason breakdown (matches your rules)
        reasons = []

        if not biz_active:
            reasons.append("Business is not active (is_active=False).")

        if ticket_is_marketplace and not biz_accepts_marketplace:
            reasons.append("Business does not accept marketplace tickets (accepts_marketplace_tickets=False).")

        if ticket_category_id is None:
            reasons.append("Ticket has no category set (category_id is null).")
        else:
            if ticket_category_id not in offered_ids:
                reasons.append(
                    f"Business does not offer this category. ticket.category_id={ticket_category_id} "
                    f"not in services_offered={sorted(list(offered_ids))[:25]}{'...' if len(offered_ids) > 25 else ''}"
                )

        # Zip source the router will use
        resolved_zip = ticket_zip or sr_zip
        if not resolved_zip:
            reasons.append("Ticket has no ZIP (ticket.service_zip empty and service_request.zip_code empty).")
        if not biz_base_zip:
            reasons.append("Business base_zip is empty (cannot match region).")

        self.stdout.write("")
        self.stdout.write("=== Eligibility Debug ===")
        self.stdout.write(f"Business: #{biz.id} '{getattr(biz, 'name', '')}'")
        self.stdout.write(f"  is_active: {biz_active}")
        self.stdout.write(f"  accepts_marketplace_tickets: {biz_accepts_marketplace}")
        self.stdout.write(f"  base_zip: '{biz_base_zip}'")
        self.stdout.write(f"  service_radius_miles: {biz_radius}")
        self.stdout.write(f"  services_offered_count: {len(offered_ids)}")
        self.stdout.write("")
        self.stdout.write(f"Ticket: #{ticket.id}")
        self.stdout.write(f"  is_marketplace: {ticket_is_marketplace}")
        self.stdout.write(f"  category_id: {ticket_category_id}")
        self.stdout.write(f"  ticket.service_zip: '{ticket_zip}'")
        self.stdout.write(f"  service_request.zip_code: '{sr_zip}'")
        self.stdout.write(f"  resolved_zip_used_for_checks: '{resolved_zip}'")
        self.stdout.write("")
        self.stdout.write(f"RESULT: eligible = {eligible}")
        self.stdout.write("")

        if eligible:
            self.stdout.write("✅ Ticket is eligible for this business.")
            return

        self.stdout.write("❌ Ticket is NOT eligible. Reasons:")
        if reasons:
            for r in reasons:
                self.stdout.write(f" - {r}")
        else:
            self.stdout.write(" - (No specific reason found here. ZIP distance lookup may be failing if geo isn't available.)")

        self.stdout.write("")
        self.stdout.write("Tips:")
        self.stdout.write(" - Confirm Business.base_zip and Business.services_offered are set correctly.")
        self.stdout.write(" - Confirm the ticket has service_zip (or the service_request has zip_code).")
        self.stdout.write(" - If you expect radius checks to work, ensure 'pgeocode' is installed and functioning.")
        self.stdout.write("")
