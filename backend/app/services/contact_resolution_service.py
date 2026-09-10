"""Deterministic recipient resolution.

Turns a free-text recipient reference (a contact's name, a team name, or a
literal email address - whatever the LLM identified as *the intended
recipient*) into real, stored email addresses, or a clear, specific reason
it couldn't. This is the ONLY code path allowed to produce an email
address for an action to use - the LLM may say a request refers to "the AI
team", but it never supplies (and this module never trusts) the actual
address. See app/agent/nodes/resolve_recipients.py for where this plugs
into plan generation, and app/repositories/contacts_repository.py for the
persistent store this queries.
"""

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, Field

from app.models.contact import ResolvedRecipient
from app.repositories.contacts_repository import ContactsRepository, get_contacts_repository


class RecipientResolutionResult(BaseModel):
    resolved: bool
    recipients: list[ResolvedRecipient] = Field(default_factory=list)
    #: Populated only when resolved is False - always a specific,
    #: user-actionable reason, never a generic "not found".
    reason: str | None = None


def resolve_recipient_reference(
    reference: str, repository: ContactsRepository | None = None
) -> RecipientResolutionResult:
    """Resolve one recipient reference. Never raises for an unresolved
    reference - callers surface `reason` as missing-information instead."""
    repository = repository or get_contacts_repository()
    reference = reference.strip()

    if not reference:
        return RecipientResolutionResult(resolved=False, reason="No recipient was specified.")

    if "@" in reference:
        return _resolve_direct_email(reference)

    team = repository.find_team_by_name(reference)
    if team is not None:
        members = repository.list_team_members(team.id)
        if not members:
            return RecipientResolutionResult(
                resolved=False, reason=f"Team '{team.name}' has no members yet."
            )
        return RecipientResolutionResult(
            resolved=True,
            recipients=[ResolvedRecipient(name=m.name, email=m.email) for m in members],
        )

    matches = repository.find_contacts_by_name(reference)
    if len(matches) == 1:
        contact = matches[0]
        return RecipientResolutionResult(
            resolved=True, recipients=[ResolvedRecipient(name=contact.name, email=contact.email)]
        )
    if len(matches) > 1:
        return RecipientResolutionResult(
            resolved=False,
            reason=f"Multiple contacts are named '{reference}' - use an email address instead.",
        )

    return RecipientResolutionResult(
        resolved=False, reason=f"No saved team or contact matches '{reference}'."
    )


def _resolve_direct_email(reference: str) -> RecipientResolutionResult:
    try:
        validated = validate_email(reference, check_deliverability=False)
    except EmailNotValidError as exc:
        return RecipientResolutionResult(
            resolved=False, reason=f"'{reference}' is not a valid email address ({exc})."
        )
    normalized_email = validated.normalized
    return RecipientResolutionResult(
        resolved=True,
        recipients=[ResolvedRecipient(name=normalized_email, email=normalized_email)],
    )
