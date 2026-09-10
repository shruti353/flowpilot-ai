"""Tests for app/services/contact_resolution_service.py - the ONLY code
path allowed to turn a recipient reference into a real email address.
Every test here uses an isolated in-memory repository passed explicitly,
so these do not depend on (or leak into) the conftest.py-provided override.
"""

import pytest

from app.repositories.contacts_repository import ContactsRepository
from app.services.contact_resolution_service import resolve_recipient_reference


@pytest.fixture
def repo() -> ContactsRepository:
    repository = ContactsRepository(":memory:")
    adarsh = repository.create_contact("Adarsh", "adarsh@example.com")
    rahul = repository.create_contact("Rahul", "rahul@example.com")
    team = repository.create_team("AI Team")
    repository.add_team_member(team.id, adarsh.id)
    repository.add_team_member(team.id, rahul.id)
    return repository


def test_resolves_a_known_contact_by_name(repo):
    result = resolve_recipient_reference("Adarsh", repo)

    assert result.resolved is True
    assert result.reason is None
    assert [r.email for r in result.recipients] == ["adarsh@example.com"]


def test_resolves_a_known_contact_by_name_case_insensitively(repo):
    result = resolve_recipient_reference("adarsh", repo)
    assert result.resolved is True


def test_resolves_a_known_team_to_all_members(repo):
    result = resolve_recipient_reference("AI Team", repo)

    assert result.resolved is True
    assert {r.email for r in result.recipients} == {"adarsh@example.com", "rahul@example.com"}


def test_resolves_team_reference_with_leading_article(repo):
    result = resolve_recipient_reference("the AI team", repo)

    assert result.resolved is True
    assert {r.email for r in result.recipients} == {"adarsh@example.com", "rahul@example.com"}


def test_resolves_a_direct_valid_email_without_any_stored_contact(repo):
    result = resolve_recipient_reference("someone-else@example.com", repo)

    assert result.resolved is True
    assert len(result.recipients) == 1
    assert result.recipients[0].email == "someone-else@example.com"


def test_rejects_an_invalid_email_looking_reference(repo):
    result = resolve_recipient_reference("adarsh@", repo)

    assert result.resolved is False
    assert "not a valid email address" in result.reason
    assert result.recipients == []


def test_unknown_contact_is_unresolved_with_a_specific_reason(repo):
    result = resolve_recipient_reference("Nobody", repo)

    assert result.resolved is False
    assert "No saved team or contact matches" in result.reason
    assert "Nobody" in result.reason


def test_unknown_team_is_unresolved_with_a_specific_reason(repo):
    result = resolve_recipient_reference("Marketing Team", repo)

    assert result.resolved is False
    assert "Marketing Team" in result.reason


def test_team_with_no_members_is_unresolved(repo):
    repo.create_team("Empty Team")

    result = resolve_recipient_reference("Empty Team", repo)

    assert result.resolved is False
    assert "no members" in result.reason


def test_ambiguous_duplicate_name_is_unresolved_rather_than_guessed(repo):
    repo.create_contact("Rahul", "rahul.second@example.com")  # a second "Rahul"

    result = resolve_recipient_reference("Rahul", repo)

    assert result.resolved is False
    assert "Multiple contacts" in result.reason
    assert result.recipients == []


def test_blank_reference_is_unresolved(repo):
    result = resolve_recipient_reference("   ", repo)
    assert result.resolved is False


def test_llm_supplied_raw_email_is_never_trusted_without_going_through_resolution(repo):
    # Regression for the core Week 5 requirement: even if a caller had a
    # raw string the LLM produced (e.g. a hallucinated address), the ONLY
    # way it ever becomes a `resolved_recipients` entry is by passing
    # through this function - there is no other path in the codebase that
    # writes to `resolved_recipients`. This test pins that a syntactically
    # plausible but never-seen address still resolves (since a directly-
    # stated, valid email is legitimately usable directly - "adarsh@example.com"
    # -> direct validated email, per spec) while a bare unresolvable NAME
    # the LLM invented (not a real address, not a saved contact/team) is
    # correctly refused rather than silently accepted.
    made_up_name_result = resolve_recipient_reference("Totally Made Up Person", repo)
    assert made_up_name_result.resolved is False
    assert made_up_name_result.recipients == []
