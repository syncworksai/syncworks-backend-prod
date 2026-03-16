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
            {
                "name": "Plumbing",
                "tasks": [
                    "Fix leaking pipe",
                    "Leaky faucet repair",
                    "Toilet repair",
                    "Drain cleaning",
                    "Water heater repair",
                    "Garbage disposal repair",
                    "Sink install",
                    "Faucet install",
                ],
            },
            {
                "name": "Electrical",
                "tasks": [
                    "Replace outlet",
                    "Diagnose breaker trip",
                    "Light fixture install",
                    "Ceiling fan install",
                    "Switch replacement",
                    "Panel inspection",
                ],
            },
            {
                "name": "HVAC",
                "tasks": [
                    "AC not cooling",
                    "Furnace maintenance",
                    "Thermostat replacement",
                    "HVAC inspection",
                    "No heat diagnosis",
                    "Airflow issue diagnosis",
                ],
            },
            {
                "name": "Handyman",
                "tasks": [
                    "Patch drywall",
                    "Install ceiling fan",
                    "TV mounting",
                    "Door repair",
                    "Shelf install",
                    "Furniture assembly",
                ],
            },
            {
                "name": "Roofing",
                "tasks": [
                    "Repair roof leak",
                    "Shingle repair",
                    "Gutter cleaning",
                    "Gutter repair",
                    "Roof inspection",
                ],
            },
            {
                "name": "Windows & Doors",
                "tasks": [
                    "Window replacement",
                    "Door repair",
                    "Door install",
                    "Window screen repair",
                    "Lock replacement",
                ],
            },
            {
                "name": "Insulation",
                "tasks": [
                    "Attic insulation install",
                    "Insulation inspection",
                    "Energy efficiency inspection",
                ],
            },
            {
                "name": "Foundation Repair",
                "tasks": [
                    "Foundation inspection",
                    "Crack repair quote",
                    "Settlement assessment",
                ],
            },
            {
                "name": "Appliance Repair",
                "tasks": [
                    "Refrigerator repair",
                    "Washer repair",
                    "Dryer repair",
                    "Dishwasher repair",
                    "Oven repair",
                    "Microwave repair",
                ],
            },
            {
                "name": "Pest Control",
                "tasks": [
                    "Ant treatment",
                    "Roach treatment",
                    "Rodent control",
                    "Termite inspection",
                    "Bed bug treatment",
                ],
            },
            {
                "name": "Pressure Washing",
                "tasks": [
                    "Driveway pressure wash",
                    "House wash",
                    "Deck pressure wash",
                    "Fence wash",
                    "Patio wash",
                ],
            },
            {
                "name": "Landscaping",
                "tasks": [
                    "Lawn mowing",
                    "Mulch install",
                    "Hedge trimming",
                    "Leaf cleanup",
                    "Yard cleanup",
                    "Planting / beds refresh",
                ],
            },
            {
                "name": "Construction & Remodeling",
                "tasks": [
                    "Kitchen remodel",
                    "Bathroom remodel",
                    "Drywall hanging",
                    "Interior painting",
                    "Flooring install",
                    "Tile install",
                    "Fence installation",
                    "Deck construction",
                ],
            },
            {
                "name": "Security & Low Voltage",
                "tasks": [
                    "Camera installation",
                    "Alarm setup",
                    "Doorbell camera install",
                    "Access control install",
                    "Low voltage wiring",
                ],
            },
            {
                "name": "Woodworking & Carpentry",
                "tasks": [
                    "Custom shelving build",
                    "Trim install",
                    "Cabinet repair",
                    "Furniture build",
                    "Wood repair",
                ],
            },
        ],
    },
    {
        "name": "Automotive & Transportation",
        "key": "automotive-transportation",
        "groups": [
            {
                "name": "Auto Repair",
                "tasks": [
                    "Engine diagnostics",
                    "Brake replacement",
                    "Battery replacement",
                    "Check engine diagnosis",
                    "Starter diagnosis",
                    "Alternator diagnosis",
                ],
            },
            {
                "name": "Mobile Mechanic",
                "tasks": [
                    "Oil change",
                    "Battery jump / replacement",
                    "On-site inspection",
                    "Minor repair visit",
                ],
            },
            {
                "name": "Detailing",
                "tasks": [
                    "Full interior detail",
                    "Exterior wash & wax",
                    "Interior shampoo",
                    "Ceramic coating consult",
                ],
            },
            {
                "name": "Towing",
                "tasks": [
                    "Tow to shop",
                    "Tow to home",
                ],
            },
            {
                "name": "Roadside Assistance",
                "tasks": [
                    "Flat tire roadside",
                    "Battery jump",
                    "Lockout service",
                    "Fuel delivery",
                ],
            },
            {
                "name": "Tint / Wrap",
                "tasks": [
                    "Window tint",
                    "Vehicle wrap consult",
                    "Paint protection film consult",
                ],
            },
            {
                "name": "Audio / Electronics",
                "tasks": [
                    "Stereo install",
                    "Speaker install",
                    "Dash cam install",
                    "Subwoofer install",
                ],
            },
        ],
    },
    {
        "name": "Ride-Share, Delivery & Mobility",
        "key": "rideshare-delivery-mobility",
        "groups": [
            {"name": "Ride-Share Driver", "tasks": ["Point-to-point ride", "Airport drop-off", "Scheduled ride"]},
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
            {"name": "Tutoring", "tasks": ["General tutoring", "Homework help"]},
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
        "name": "Events, Creative & Lifestyle",
        "key": "events-creative-lifestyle",
        "groups": [
            {"name": "Event Planning", "tasks": ["Corporate event setup", "Event teardown", "Party setup / breakdown"]},
            {"name": "Photography", "tasks": ["Wedding photography", "Portrait session", "Event photography"]},
            {"name": "Videography", "tasks": ["Event videography", "Promo video shoot"]},
            {"name": "DJ / Audio", "tasks": ["Birthday DJ", "Sound setup"]},
            {"name": "Inflatables & Party Rentals", "tasks": ["Bounce house rental", "Water slide rental"]},
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
            {"name": "Notary", "tasks": ["Document notarization", "Mobile notary visit"]},
            {"name": "Insurance", "tasks": ["Insurance quote request", "Policy review"]},
            {"name": "Tax Help", "tasks": ["Personal tax help", "Business tax help"]},
        ],
    },
    {
        "name": "Health, Wellness & Fitness",
        "key": "health-wellness-fitness",
        "groups": [
            {"name": "Personal Training", "tasks": ["In-home training", "Mobility assessment"]},
            {"name": "Massage Therapy", "tasks": ["Sports massage", "Relaxation massage"]},
            {"name": "Nutrition Coaching", "tasks": ["Meal planning", "Macro coaching"]},
            {"name": "Martial Arts", "tasks": ["Private martial arts lesson", "Beginner martial arts coaching"]},
            {"name": "Dance", "tasks": ["Private dance lesson", "Dance coaching"]},
        ],
    },
    {
        "name": "Pets & Animal Services",
        "key": "pets-animal-services",
        "groups": [
            {"name": "Pet Grooming", "tasks": ["Dog grooming", "Cat grooming", "Bath and nail trim"]},
            {"name": "Pet Sitting", "tasks": ["Pet sitting visit", "Overnight pet sitting"]},
            {"name": "Dog Walking", "tasks": ["Dog walk", "Recurring dog walking"]},
            {"name": "Pet Training", "tasks": ["Obedience training", "Behavior training"]},
        ],
    },
    {
        "name": "Tech, IT & Digital Services",
        "key": "tech-it-digital-services",
        "groups": [
            {"name": "Computer Repair", "tasks": ["PC repair", "Virus removal", "Laptop troubleshooting"]},
            {"name": "Network Setup", "tasks": ["Wi-Fi setup", "Router install", "Network troubleshooting"]},
            {"name": "Phone / Device Help", "tasks": ["Phone setup", "Device transfer", "Tablet troubleshooting"]},
            {"name": "Web Design & Development", "tasks": ["Website update", "Landing page build", "Website redesign"]},
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