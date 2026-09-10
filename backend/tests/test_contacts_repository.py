"""Tests for the SQLite-backed Contacts/Teams repository
(app/repositories/contacts_repository.py). Each test gets its own
in-memory database via `ContactsRepository(":memory:")` directly - these
tests do not rely on the module-level singleton or the conftest.py
override (that's exercised separately by tests that go through the API).
"""

import pytest

from app.repositories.contacts_repository import (
    ContactNotFoundError,
    ContactsRepository,
    TeamNotFoundError,
)


@pytest.fixture
def repo() -> ContactsRepository:
    return ContactsRepository(":memory:")


# --- Contacts ------------------------------------------------------------


def test_create_and_retrieve_contact(repo):
    created = repo.create_contact("Adarsh", "adarsh@example.com")
    fetched = repo.get_contact(created.id)

    assert fetched.name == "Adarsh"
    assert fetched.email == "adarsh@example.com"


def test_get_unknown_contact_raises(repo):
    with pytest.raises(ContactNotFoundError):
        repo.get_contact(999)


def test_update_contact_name_and_email(repo):
    contact = repo.create_contact("Adarsh", "adarsh@example.com")

    updated = repo.update_contact(contact.id, name="Adarsh K", email="adarsh.k@example.com")

    assert updated.name == "Adarsh K"
    assert updated.email == "adarsh.k@example.com"
    assert repo.get_contact(contact.id).email == "adarsh.k@example.com"


def test_update_contact_partial_only_changes_given_field(repo):
    contact = repo.create_contact("Adarsh", "adarsh@example.com")

    updated = repo.update_contact(contact.id, name="Adarsh K")

    assert updated.name == "Adarsh K"
    assert updated.email == "adarsh@example.com"  # untouched


def test_update_unknown_contact_raises(repo):
    with pytest.raises(ContactNotFoundError):
        repo.update_contact(999, name="Nobody")


def test_creating_duplicate_email_returns_existing_contact_idempotently(repo):
    first = repo.create_contact("Adarsh", "adarsh@example.com")
    second = repo.create_contact("Adarsh Again", "ADARSH@EXAMPLE.COM")  # case-insensitive

    assert second.id == first.id
    assert second.name == "Adarsh"  # original row untouched, not silently renamed
    assert len(repo.list_contacts()) == 1


def test_list_contacts_returns_all(repo):
    repo.create_contact("Adarsh", "adarsh@example.com")
    repo.create_contact("Rahul", "rahul@example.com")

    names = {c.name for c in repo.list_contacts()}
    assert names == {"Adarsh", "Rahul"}


def test_find_contacts_by_name_is_case_insensitive(repo):
    repo.create_contact("Adarsh", "adarsh@example.com")

    assert len(repo.find_contacts_by_name("adarsh")) == 1
    assert len(repo.find_contacts_by_name("ADARSH")) == 1
    assert repo.find_contacts_by_name("nobody") == []


def test_find_contacts_by_name_returns_all_ambiguous_matches(repo):
    repo.create_contact("Rahul", "rahul1@example.com")
    repo.create_contact("Rahul", "rahul2@example.com")

    assert len(repo.find_contacts_by_name("Rahul")) == 2


# --- Teams -----------------------------------------------------------------


def test_create_and_retrieve_team(repo):
    created = repo.create_team("AI Team")

    fetched = repo.get_team(created.id)
    assert fetched.name == "AI Team"


def test_get_unknown_team_raises(repo):
    with pytest.raises(TeamNotFoundError):
        repo.get_team(999)


def test_creating_duplicate_team_name_returns_existing_team_idempotently(repo):
    first = repo.create_team("AI Team")
    second = repo.create_team("ai team")  # case-insensitive
    third = repo.create_team("the AI Team")  # leading article also normalized

    assert second.id == first.id
    assert third.id == first.id


def test_add_team_member_and_retrieve_with_multiple_members(repo):
    team = repo.create_team("AI Team")
    adarsh = repo.create_contact("Adarsh", "adarsh@example.com")
    rahul = repo.create_contact("Rahul", "rahul@example.com")

    repo.add_team_member(team.id, adarsh.id)
    repo.add_team_member(team.id, rahul.id)

    members = repo.list_team_members(team.id)
    assert {m.email for m in members} == {"adarsh@example.com", "rahul@example.com"}

    with_members = repo.get_team_with_members(team.id)
    assert with_members.name == "AI Team"
    assert {m.email for m in with_members.members} == {"adarsh@example.com", "rahul@example.com"}


def test_adding_duplicate_team_member_is_a_no_op(repo):
    team = repo.create_team("AI Team")
    adarsh = repo.create_contact("Adarsh", "adarsh@example.com")

    repo.add_team_member(team.id, adarsh.id)
    repo.add_team_member(team.id, adarsh.id)  # duplicate membership

    assert len(repo.list_team_members(team.id)) == 1


def test_add_member_to_unknown_team_raises(repo):
    adarsh = repo.create_contact("Adarsh", "adarsh@example.com")
    with pytest.raises(TeamNotFoundError):
        repo.add_team_member(999, adarsh.id)


def test_add_unknown_contact_to_team_raises(repo):
    team = repo.create_team("AI Team")
    with pytest.raises(ContactNotFoundError):
        repo.add_team_member(team.id, 999)


def test_team_with_no_members_returns_empty_list(repo):
    team = repo.create_team("Empty Team")
    assert repo.list_team_members(team.id) == []


def _all_team_ids(repo: ContactsRepository) -> set[int]:
    # No list_teams() on the repository yet (not needed by any current
    # caller) - this test only needs to confirm no second row was created.
    with repo._connect() as conn:  # noqa: SLF001 - test-only introspection
        rows = conn.execute("SELECT id FROM teams").fetchall()
    return {row["id"] for row in rows}
