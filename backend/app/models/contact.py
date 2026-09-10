"""Contacts/Teams schema: FlowPilot's persistent memory of *people*.

These records are the ONLY source of truth for a real email address. The
LLM may say a request refers to "the AI team" or "Adarsh" - it never
supplies (and is never trusted for) the actual address. See
app/services/contact_resolution_service.py for the deterministic lookup
that turns a reference into these records, and
app/repositories/contacts_repository.py for the SQLite-backed persistence
that survives a backend restart (unlike app/repositories/plan_repository.py,
which is intentionally in-memory only).
"""

from pydantic import BaseModel, EmailStr, Field


class Contact(BaseModel):
    id: int
    name: str
    email: EmailStr


class Team(BaseModel):
    id: int
    name: str


class TeamWithMembers(Team):
    members: list[Contact] = Field(default_factory=list)


class ResolvedRecipient(BaseModel):
    """One deterministically-resolved recipient - either a saved Contact, or
    a directly-supplied, syntactically-validated email address with no
    saved record (no `id`, since it may not correspond to any stored
    contact). This is the ONLY shape that reaches an email action's
    `resolved_recipients` parameter - see
    app/services/contact_resolution_service.py.
    """

    name: str
    email: EmailStr


class CreateContactRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr


class UpdateContactRequest(BaseModel):
    """At least one of name/email should be set; both are optional so a
    caller can patch just the field they mean to change."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None


class CreateTeamRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class AddTeamMemberRequest(BaseModel):
    """Either reference an existing contact by id, or create-or-reuse one
    inline by name+email in the same call (supports "my AI team members are
    Adarsh at adarsh@example.com..." with one call per member, no separate
    contact-creation round trip required)."""

    contact_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
