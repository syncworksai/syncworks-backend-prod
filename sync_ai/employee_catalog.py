"""AI employee templates. Capabilities are declarations, not granted connector access.

Adding a role here never allows it to call a provider or perform side effects.
A future executor must authorize each tool operation independently.
"""
from __future__ import annotations

ROLES = (
    ("chief_of_staff", "Chief of Staff", "Coordinate priorities, create plans and delegate assignments",
     ("planning", "calendar_read", "assignment_routing")),
    ("personal_trainer", "Personal Trainer", "Plan workouts and review fitness progress",
     ("fitness_planning", "health_read", "calendar_read")),
    ("finance_manager", "Finance Manager", "Review budgets, expenses and financial reports",
     ("budget_analysis", "finance_read")),
    ("business_manager", "Business Manager", "Review jobs, clients and business operations",
     ("business_read", "ticket_review", "operations_planning")),
    ("property_manager", "Property Manager", "Review tenants, maintenance and property schedules",
     ("property_read", "maintenance_triage")),
    ("marketing_manager", "Marketing Manager", "Plan campaigns and prepare marketing content",
     ("campaign_planning", "content_drafting")),
    ("sales_representative", "Sales Representative", "Review and organize leads and draft outreach",
     ("crm_read", "lead_qualification", "outreach_drafting")),
    ("customer_service", "Customer Service Representative", "Triage customer inquiries and draft replies",
     ("inbox_read", "support_triage", "reply_drafting")),
    ("executive_assistant", "Executive Assistant", "Plan appointments and organize administrative work",
     ("calendar_read", "schedule_planning", "inbox_read")),
    ("research_analyst", "Research Analyst", "Research markets, competitors and opportunities",
     ("research_planning", "public_web_research")),
    ("lead_scout", "Lead Scout", "Discover and qualify potential customers and partner businesses",
     ("public_web_research", "lead_qualification", "crm_draft")),
    ("events_scout", "Events & Job Fair Scout", "Discover relevant fairs, networking and promotional events",
     ("public_web_research", "event_discovery", "event_shortlisting")),
)

CATALOG = {
    slug: {
        "id": slug,
        "name": name,
        "description": description,
        "capabilities": list(capabilities),
        "beta_price_cents": 0,
        "currency": "USD",
        "billing_enabled": False,
        "execution_enabled": False,
        "requires_approval_for_writes": True,
    }
    for slug, name, description, capabilities in ROLES
}
