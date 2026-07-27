from __future__ import annotations

from dataclasses import dataclass

from .context import WorkspaceContext


@dataclass(frozen=True)
class DraftDefinition:
    action_type: str
    title: str
    workspace: str
    guidance: str


DRAFT_DEFINITIONS = {
    "ticket_reply": DraftDefinition(
        action_type="ticket_reply",
        title="Ticket or customer reply",
        workspace="any",
        guidance=(
            "Write a concise, professional reply suitable for a ticket conversation. "
            "Do not claim work is complete, scheduled, approved, or paid unless the "
            "instruction explicitly states that confirmed fact."
        ),
    ),
    "lead_follow_up": DraftDefinition(
        action_type="lead_follow_up",
        title="Lead follow-up",
        workspace="business",
        guidance=(
            "Write a warm, direct business follow-up that invites a clear next step. "
            "Do not invent pricing, availability, prior conversations, or promises."
        ),
    ),
    "schedule_proposal": DraftDefinition(
        action_type="schedule_proposal",
        title="Schedule-change proposal",
        workspace="any",
        guidance=(
            "Write a proposed schedule message. Clearly label dates or times as proposed "
            "and requiring confirmation. Do not state that a calendar or job was changed."
        ),
    ),
}


def get_draft_definition(action_type: str, context: WorkspaceContext) -> DraftDefinition:
    normalized = str(action_type or "").strip().lower()
    definition = DRAFT_DEFINITIONS.get(normalized)
    if definition is None:
        raise ValueError("Unsupported SYNC draft type.")
    if definition.workspace == "business" and context.workspace != "business":
        raise PermissionError("This draft type requires Business SYNC.")
    return definition


def build_draft_prompt(
    *,
    definition: DraftDefinition,
    instruction: str,
    context: WorkspaceContext,
) -> str:
    return (
        f"Prepare an editable {definition.title.lower()} draft.\n"
        f"Drafting guidance: {definition.guidance}\n"
        f"User instruction: {instruction}\n"
        "Return only the finished draft text. Do not include analysis, labels, "
        "markdown fences, or claims that the draft was sent. "
        f"Workspace: {context.workspace}. Role: {context.role}."
    )
