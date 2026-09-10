"""SQLite-backed persistence for contacts and teams.

Unlike PlanRepository (app/repositories/plan_repository.py - in-memory,
intentionally lost on restart), contact/team data is real user data that
must survive a backend restart. Uses the stdlib `sqlite3` module directly -
no ORM - matching this codebase's preference for small, explicit,
dependency-light persistence code.

A fresh connection is opened per call for a real (file-backed) database,
which sidesteps sqlite3's cross-thread-safety caveats entirely and is
plenty fast at local/single-user scale. An in-memory database (":memory:",
used by tests) is per-connection by SQLite's own design, so a single
connection is held open for the lifetime of the repository instance in
that case instead.

Duplicate handling is idempotent by natural key, not an error: creating a
contact with an email that already exists (case-insensitively) returns the
existing row; creating a team with an existing name likewise; adding an
already-present team member is a no-op. This matches how a user naturally
re-states known contacts ("my AI team is Adarsh and Rahul") without needing
to remember whether they already saved them, and is exactly what the
UNIQUE / PRIMARY KEY constraints below make trivial to guarantee.
"""

import re
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.models.contact import Contact, Team, TeamWithMembers

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS team_members (
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    PRIMARY KEY (team_id, contact_id)
);
"""

#: A team name is looked up ignoring case and a leading article, so "AI
#: Team", "ai team", and "the AI team" are all the same team.
_LEADING_ARTICLE = re.compile(r"^\s*the\s+", re.IGNORECASE)


def normalize_team_name(name: str) -> str:
    return _LEADING_ARTICLE.sub("", name).strip().casefold()


class ContactNotFoundError(Exception):
    def __init__(self, contact_id: int) -> None:
        self.contact_id = contact_id
        super().__init__(f"No contact found with id {contact_id}.")


class TeamNotFoundError(Exception):
    def __init__(self, team_id: int) -> None:
        self.team_id = team_id
        super().__init__(f"No team found with id {team_id}.")


class MembershipNotFoundError(Exception):
    """Raised when removing a member who isn't (or is no longer) on the team."""

    def __init__(self, team_id: int, contact_id: int) -> None:
        self.team_id = team_id
        self.contact_id = contact_id
        super().__init__(f"Contact {contact_id} is not a member of team {team_id}.")


class DuplicateEmailError(Exception):
    """Raised only by update_contact - create_contact itself is idempotent-by-
    email (see module docstring) and never raises this. Renaming an existing
    contact's email onto one already used by a DIFFERENT contact has no safe
    idempotent interpretation, unlike creation, so it's rejected outright
    instead of silently merging two contacts or letting a raw UNIQUE-
    constraint IntegrityError leak to callers."""

    def __init__(self, email: str) -> None:
        self.email = email
        super().__init__(f"A contact with email '{email}' already exists.")


class DuplicateTeamNameError(Exception):
    """Raised only by update_team_name - see DuplicateEmailError for why
    rename (unlike create_team's idempotent reuse) must reject a collision."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"A team named '{name}' already exists.")


class ContactsRepository:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._db_path = db_path
        self._memory_conn: sqlite3.Connection | None = None
        if db_path == ":memory:":
            # check_same_thread=False: a TestClient-driven FastAPI app runs
            # request handlers on a different thread than the one that
            # constructed this repository (e.g. a pytest fixture). There is
            # no real concurrent access risk in that scenario - requests
            # are handled one at a time against this single connection.
            self._memory_conn = sqlite3.connect(db_path, check_same_thread=False)
            self._memory_conn.row_factory = sqlite3.Row
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = self._memory_conn or sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            if conn is not self._memory_conn:
                conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # --- Contacts -----------------------------------------------------

    def create_contact(self, name: str, email: str) -> Contact:
        name = name.strip()
        email = email.strip()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, name, email FROM contacts WHERE email = ? COLLATE NOCASE", (email,)
            ).fetchone()
            if existing is not None:
                return Contact(id=existing["id"], name=existing["name"], email=existing["email"])

            cursor = conn.execute(
                "INSERT INTO contacts (name, email) VALUES (?, ?)", (name, email)
            )
            return Contact(id=cursor.lastrowid, name=name, email=email)

    def get_contact(self, contact_id: int) -> Contact:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, email FROM contacts WHERE id = ?", (contact_id,)
            ).fetchone()
        if row is None:
            raise ContactNotFoundError(contact_id)
        return Contact(id=row["id"], name=row["name"], email=row["email"])

    def find_contact_by_email(self, email: str) -> Contact | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, email FROM contacts WHERE email = ? COLLATE NOCASE", (email.strip(),)
            ).fetchone()
        return Contact(id=row["id"], name=row["name"], email=row["email"]) if row else None

    def find_contacts_by_name(self, name: str) -> list[Contact]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, email FROM contacts WHERE name = ? COLLATE NOCASE ORDER BY id",
                (name.strip(),),
            ).fetchall()
        return [Contact(id=row["id"], name=row["name"], email=row["email"]) for row in rows]

    def list_contacts(self) -> list[Contact]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, name, email FROM contacts ORDER BY id").fetchall()
        return [Contact(id=row["id"], name=row["name"], email=row["email"]) for row in rows]

    def update_contact(
        self, contact_id: int, name: str | None = None, email: str | None = None
    ) -> Contact:
        current = self.get_contact(contact_id)
        new_name = name.strip() if name is not None else current.name
        new_email = email.strip() if email is not None else current.email

        if new_email.casefold() != current.email.casefold():
            colliding = self.find_contact_by_email(new_email)
            if colliding is not None and colliding.id != contact_id:
                raise DuplicateEmailError(new_email)

        with self._connect() as conn:
            conn.execute(
                "UPDATE contacts SET name = ?, email = ? WHERE id = ?",
                (new_name, new_email, contact_id),
            )
        return Contact(id=contact_id, name=new_name, email=new_email)

    def delete_contact(self, contact_id: int) -> None:
        self.get_contact(contact_id)  # 404s cleanly if it doesn't exist
        with self._connect() as conn:
            # ON DELETE CASCADE (team_members.contact_id) removes this
            # contact's memberships automatically - no orphaned rows.
            conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))

    # --- Teams ----------------------------------------------------------

    def create_team(self, name: str) -> Team:
        name = name.strip()
        # Uses the same normalized (case/leading-article-insensitive) match
        # as find_team_by_name, so "AI Team" and "the AI Team" are always
        # treated as the same team - never two separate rows that
        # resolution could then pick between inconsistently.
        existing = self.find_team_by_name(name)
        if existing is not None:
            return existing

        with self._connect() as conn:
            cursor = conn.execute("INSERT INTO teams (name) VALUES (?)", (name,))
            return Team(id=cursor.lastrowid, name=name)

    def get_team(self, team_id: int) -> Team:
        with self._connect() as conn:
            row = conn.execute("SELECT id, name FROM teams WHERE id = ?", (team_id,)).fetchone()
        if row is None:
            raise TeamNotFoundError(team_id)
        return Team(id=row["id"], name=row["name"])

    def list_teams(self) -> list[Team]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, name FROM teams ORDER BY id").fetchall()
        return [Team(id=row["id"], name=row["name"]) for row in rows]

    def update_team_name(self, team_id: int, name: str) -> Team:
        self.get_team(team_id)  # 404s cleanly if it doesn't exist
        name = name.strip()

        existing = self.find_team_by_name(name)
        if existing is not None and existing.id != team_id:
            raise DuplicateTeamNameError(name)

        with self._connect() as conn:
            conn.execute("UPDATE teams SET name = ? WHERE id = ?", (name, team_id))
        return Team(id=team_id, name=name)

    def delete_team(self, team_id: int) -> None:
        self.get_team(team_id)  # 404s cleanly if it doesn't exist
        with self._connect() as conn:
            # ON DELETE CASCADE (team_members.team_id) removes this team's
            # memberships automatically - no orphaned rows.
            conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))

    def find_team_by_name(self, name: str) -> Team | None:
        normalized = normalize_team_name(name)
        with self._connect() as conn:
            rows = conn.execute("SELECT id, name FROM teams").fetchall()
        for row in rows:
            if normalize_team_name(row["name"]) == normalized:
                return Team(id=row["id"], name=row["name"])
        return None

    def add_team_member(self, team_id: int, contact_id: int) -> None:
        # Existence checks first, so a foreign-key failure never masks a
        # clearer "team/contact not found" error.
        self.get_team(team_id)
        self.get_contact(contact_id)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO team_members (team_id, contact_id) VALUES (?, ?)",
                (team_id, contact_id),
            )

    def is_team_member(self, team_id: int, contact_id: int) -> bool:
        self.get_team(team_id)  # 404s cleanly if it doesn't exist
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM team_members WHERE team_id = ? AND contact_id = ?",
                (team_id, contact_id),
            ).fetchone()
        return row is not None

    def remove_team_member(self, team_id: int, contact_id: int) -> None:
        self.get_team(team_id)
        self.get_contact(contact_id)
        if not self.is_team_member(team_id, contact_id):
            raise MembershipNotFoundError(team_id, contact_id)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM team_members WHERE team_id = ? AND contact_id = ?",
                (team_id, contact_id),
            )

    def list_team_members(self, team_id: int) -> list[Contact]:
        self.get_team(team_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT contacts.id, contacts.name, contacts.email
                FROM team_members
                JOIN contacts ON contacts.id = team_members.contact_id
                WHERE team_members.team_id = ?
                ORDER BY contacts.id
                """,
                (team_id,),
            ).fetchall()
        return [Contact(id=row["id"], name=row["name"], email=row["email"]) for row in rows]

    def get_team_with_members(self, team_id: int) -> TeamWithMembers:
        team = self.get_team(team_id)
        members = self.list_team_members(team_id)
        return TeamWithMembers(id=team.id, name=team.name, members=members)


_repository: ContactsRepository | None = None
_repository_override: ContactsRepository | None = None


def set_contacts_repository(repository: ContactsRepository | None) -> None:
    """Override the repository used application-wide. Pass None to reset.

    Intended for tests: `contacts_repository.set_contacts_repository(ContactsRepository())`
    (defaults to an in-memory database - see the class docstring).
    """
    global _repository_override
    _repository_override = repository


def get_contacts_repository() -> ContactsRepository:
    if _repository_override is not None:
        return _repository_override

    global _repository
    if _repository is None:
        from app.core.config import get_settings

        _repository = ContactsRepository(get_settings().contacts_db_path)
    return _repository
