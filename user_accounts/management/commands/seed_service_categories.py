# backend/user_accounts/management/commands/seed_service_categories.py
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from user_accounts.models import ServiceCategory


# 3-level taxonomy:
# ROOT (Industry) -> GROUP (Core Service) -> LEAF (Atomic Tasks; ticket-selectable)
TAXONOMY = [
    {
        "name": "Home & Property Services",
        "key": "home-property-services",
        "groups": [
            {"name": "Plumbing", "tasks": ["Fix leaking pipe", "Install faucet"]},
            {"name": "Electrical", "tasks": ["Replace outlet", "Diagnose breaker trip"]},
            {"name": "HVAC", "tasks": ["AC not cooling", "Furnace maintenance"]},
            {"name": "Handyman", "tasks": ["Patch drywall", "Install ceiling fan"]},
            {"name": "Roofing", "tasks": ["Repair roof leak"]},
            {"name": "Windows & Doors", "tasks": ["Window replacement"]},
            {"name": "Insulation", "tasks": ["Attic insulation install", "Insulation inspection"]},
            {"name": "Foundation Repair", "tasks": ["Foundation inspection", "Crack repair quote"]},
        ],
    },
    {
        "name": "Automotive & Transportation",
        "key": "automotive-transportation",
        "groups": [
            {"name": "Auto Repair", "tasks": ["Engine diagnostics", "Brake replacement"]},
            {"name": "Mobile Mechanic", "tasks": ["Oil change", "Battery jump / replacement"]},
            {"name": "Detailing", "tasks": ["Full interior detail", "Exterior wash & wax"]},
            {"name": "Towing", "tasks": ["Tow to shop", "Tow to home"]},
            {"name": "Roadside Assistance", "tasks": ["Flat tire roadside", "Battery jump"]},
            {"name": "Fleet Maintenance", "tasks": ["Fleet oil change", "Fleet inspection"]},
        ],
    },
    {
        "name": "Ride-Share, Delivery & Mobility",
        "key": "rideshare-delivery-mobility",
        "groups": [
            {"name": "Ride-Share Driver", "tasks": ["Point-to-point ride", "Airport drop-off"]},
            {"name": "Package Delivery", "tasks": ["Same-day package delivery", "Scheduled pickup"]},
            {"name": "Food Delivery", "tasks": ["Food delivery", "Grocery delivery"]},
            {"name": "Medical Transport", "tasks": ["Non-emergency medical ride", "Clinic pickup/drop-off"]},
            {"name": "Senior Transport", "tasks": ["Senior transport appointment", "Errand transport"]},
        ],
    },
    {
        "name": "Family, Kids & Personal Care",
        "key": "family-kids-personal-care",
        "groups": [
            {"name": "Babysitting", "tasks": ["Evening babysitting", "Overnight care"]},
            {"name": "Nanny Services", "tasks": ["School pickup", "After-school care"]},
            {"name": "Elder Care", "tasks": ["Medication reminders", "Companion care"]},
            {"name": "Personal Assistant", "tasks": ["Errand running", "Appointment scheduling"]},
        ],
    },
    {
        "name": "Cleaning & Maintenance",
        "key": "cleaning-maintenance",
        "groups": [
            {"name": "Residential Cleaning", "tasks": ["Standard house clean", "Bathroom sanitation"]},
            {"name": "Commercial Cleaning", "tasks": ["Office nightly cleaning", "Breakroom deep clean"]},
            {"name": "Janitorial", "tasks": ["Trash & restock", "Floor mop & sweep"]},
            {"name": "Deep Cleaning", "tasks": ["Deep kitchen clean", "Carpet shampoo"]},
            {"name": "Move-In / Move-Out", "tasks": ["Move-out deep clean", "Move-in prep clean"]},
            {"name": "Post-Construction", "tasks": ["Post-construction cleanup"]},
        ],
    },
    {
        "name": "Lawn, Outdoor & Environmental",
        "key": "lawn-outdoor-environmental",
        "groups": [
            {"name": "Lawn Care", "tasks": ["Lawn mowing", "Edging"]},
            {"name": "Landscaping", "tasks": ["Mulch install", "Planting / beds refresh"]},
            {"name": "Tree Services", "tasks": ["Tree trimming", "Tree removal"]},
            {"name": "Snow Removal", "tasks": ["Snow plowing", "Salt / de-ice"]},
            {"name": "Pressure Washing", "tasks": ["Driveway pressure wash", "Siding wash"]},
        ],
    },
    {
        "name": "Construction, Trades & Skilled Labor",
        "key": "construction-trades-skilled-labor",
        "groups": [
            {"name": "General Contracting", "tasks": ["Project estimate", "Site walkthrough"]},
            {"name": "Renovation", "tasks": ["Kitchen remodel", "Bathroom remodel"]},
            {"name": "Remodeling", "tasks": ["Deck construction", "Fence installation"]},
            {"name": "Framing", "tasks": ["Wall framing", "Door framing"]},
            {"name": "Masonry", "tasks": ["Concrete pouring", "Block repair"]},
            {"name": "Drywall", "tasks": ["Drywall hanging", "Tape & mud"]},
        ],
    },
    {
        "name": "Tech, IT & Digital Services",
        "key": "tech-it-digital-services",
        "groups": [
            {"name": "IT Support", "tasks": ["Remote troubleshooting", "Device setup"]},
            {"name": "Computer Repair", "tasks": ["PC repair", "Virus removal"]},
            {"name": "Network Setup", "tasks": ["Wi-Fi setup", "Router install"]},
            {"name": "Smart Home Install", "tasks": ["Smart thermostat install", "Smart lock install"]},
            {"name": "Security Systems", "tasks": ["Camera installation", "Alarm setup"]},
            {"name": "POS / Business Tech", "tasks": ["POS system setup", "Printer setup"]},
        ],
    },
    {
        "name": "Moving, Storage & Logistics",
        "key": "moving-storage-logistics",
        "groups": [
            {"name": "Local Moving", "tasks": ["Apartment move", "Furniture transport"]},
            {"name": "Long-Distance Moving", "tasks": ["Long-distance move quote", "Load/unload help"]},
            {"name": "Junk Removal", "tasks": ["Junk haul-away", "Appliance removal"]},
            {"name": "Storage", "tasks": ["Storage pickup", "Storage drop-off"]},
        ],
    },
    {
        "name": "Events, Creative & Lifestyle",
        "key": "events-creative-lifestyle",
        "groups": [
            {"name": "Event Planning", "tasks": ["Corporate event setup", "Event teardown"]},
            {"name": "Photography", "tasks": ["Wedding photography", "Portrait session"]},
            {"name": "Videography", "tasks": ["Event videography", "Promo video shoot"]},
            {"name": "DJ / Audio", "tasks": ["Birthday DJ", "Sound setup"]},
            {"name": "Decorating", "tasks": ["Balloon/decor setup", "Backdrop install"]},
        ],
    },
    {
        "name": "Business, Admin & Professional",
        "key": "business-admin-professional",
        "groups": [
            {"name": "Bookkeeping", "tasks": ["Monthly bookkeeping", "Expense categorization"]},
            {"name": "Accounting", "tasks": ["Payroll processing", "Quarterly close support"]},
            {"name": "Virtual Assistant", "tasks": ["Appointment scheduling", "Inbox cleanup"]},
            {"name": "Consulting", "tasks": ["Process audit", "Ops improvement plan"]},
            {"name": "Marketing", "tasks": ["Social media posting", "Website updates"]},
            {"name": "CRM / Admin", "tasks": ["CRM cleanup", "Data entry batch"]},
        ],
    },
    {
        "name": "Health, Wellness & Fitness",
        "key": "health-wellness-fitness",
        "groups": [
            {"name": "Personal Training", "tasks": ["In-home training", "Mobility assessment"]},
            {"name": "Physical Therapy", "tasks": ["Post-injury rehab", "Stretch therapy"]},
            {"name": "Massage Therapy", "tasks": ["Sports massage", "Relaxation massage"]},
            {"name": "Nutrition Coaching", "tasks": ["Meal planning", "Macro coaching"]},
        ],
    },
]


def _slugify_key(s: str) -> str:
    s = (s or "").strip().lower()
    s = (
        s.replace("&", "and")
        .replace("/", "-")
        .replace("(", "")
        .replace(")", "")
        .replace("—", "-")
        .replace("–", "-")
        .replace("’", "")
        .replace("'", "")
        .replace(",", "")
    )
    # keep it slug-like without importing slugify
    parts = []
    for part in s.split():
        cleaned = "".join(ch for ch in part if ch.isalnum() or ch == "-").strip("-")
        if cleaned:
            parts.append(cleaned)
    out = "-".join(parts)
    return out[:140]


def upsert_category(name: str, key: str, parent: ServiceCategory | None, sort_order: int) -> ServiceCategory:
    obj, _created = ServiceCategory.objects.get_or_create(
        key=key,
        defaults={
            "name": name,
            "parent": parent,
            "is_active": True,
            "sort_order": sort_order,
        },
    )

    changed = False
    if obj.name != name:
        obj.name = name
        changed = True
    if obj.parent_id != (parent.id if parent else None):
        obj.parent = parent
        changed = True
    if obj.sort_order != sort_order:
        obj.sort_order = sort_order
        changed = True
    if not obj.is_active:
        obj.is_active = True
        changed = True

    if changed:
        obj.save()

    return obj


class Command(BaseCommand):
    help = "Seeds universal ServiceCategory taxonomy (ROOT -> GROUP -> LEAF tasks)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="DANGER: deletes all ServiceCategory rows before seeding.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options.get("reset"):
            self.stdout.write(self.style.WARNING("RESET: deleting all ServiceCategory rows..."))
            ServiceCategory.objects.all().delete()

        self.stdout.write("Seeding ServiceCategory taxonomy...")

        # ROOTS
        root_objs: dict[str, ServiceCategory] = {}
        root_sort = 10
        for root in TAXONOMY:
            root_obj = upsert_category(
                name=root["name"],
                key=root["key"],
                parent=None,
                sort_order=root_sort,
            )
            root_objs[root["key"]] = root_obj
            root_sort += 10

        # GROUPS + LEAF TASKS
        for root in TAXONOMY:
            root_parent = root_objs[root["key"]]
            group_sort = 10

            for grp in root.get("groups", []):
                group_name = grp["name"]
                group_key = f"{root['key']}--{_slugify_key(group_name)}"
                group_obj = upsert_category(
                    name=group_name,
                    key=group_key,
                    parent=root_parent,
                    sort_order=group_sort,
                )
                group_sort += 10

                task_sort = 10
                for task_name in grp.get("tasks", []):
                    task_key = f"{group_key}--{_slugify_key(task_name)}"
                    upsert_category(
                        name=task_name,
                        key=task_key,
                        parent=group_obj,
                        sort_order=task_sort,
                    )
                    task_sort += 10

        self.stdout.write(self.style.SUCCESS("✅ ServiceCategory seeding complete."))
