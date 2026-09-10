"""Minimal CRUD for the Teams store (see app/repositories/contacts_repository.py).

Adding a member accepts either an existing contact_id, or an inline
name+email that is created-or-reused in the same call - so "my AI team
members are Adarsh at adarsh@example.com and Rahul at rahul@example.com"
can be saved with one call per member and no separate contact-creation
round trip.
"""

from fastapi import APIRouter, HTTPException

from app.models.contact import (
    AddTeamMemberRequest,
    Contact,
    CreateTeamRequest,
    Team,
    TeamWithMembers,
    UpdateTeamRequest,
)
from app.repositories.contacts_repository import (
    ContactNotFoundError,
    DuplicateTeamNameError,
    MembershipNotFoundError,
    TeamNotFoundError,
    get_contacts_repository,
)

router = APIRouter(prefix="/teams", tags=["teams"])


def _team_not_found(team_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No team found with id {team_id}.")


def _contact_not_found(contact_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No contact found with id {contact_id}.")


@router.post("", response_model=Team)
async def create_team(payload: CreateTeamRequest) -> Team:
    return get_contacts_repository().create_team(payload.name)


@router.get("", response_model=list[Team])
async def list_teams() -> list[Team]:
    return get_contacts_repository().list_teams()


@router.get("/{team_id}", response_model=TeamWithMembers)
async def get_team(team_id: int) -> TeamWithMembers:
    try:
        return get_contacts_repository().get_team_with_members(team_id)
    except TeamNotFoundError as exc:
        raise _team_not_found(team_id) from exc


@router.patch("/{team_id}", response_model=Team)
async def rename_team(team_id: int, payload: UpdateTeamRequest) -> Team:
    try:
        return get_contacts_repository().update_team_name(team_id, payload.name)
    except TeamNotFoundError as exc:
        raise _team_not_found(team_id) from exc
    except DuplicateTeamNameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{team_id}", status_code=204)
async def delete_team(team_id: int) -> None:
    try:
        get_contacts_repository().delete_team(team_id)
    except TeamNotFoundError as exc:
        raise _team_not_found(team_id) from exc


@router.get("/{team_id}/members", response_model=list[Contact])
async def list_team_members(team_id: int) -> list[Contact]:
    try:
        return get_contacts_repository().list_team_members(team_id)
    except TeamNotFoundError as exc:
        raise _team_not_found(team_id) from exc


@router.post("/{team_id}/members", response_model=TeamWithMembers)
async def add_team_member(team_id: int, payload: AddTeamMemberRequest) -> TeamWithMembers:
    repository = get_contacts_repository()

    if payload.contact_id is None and (payload.name is None or payload.email is None):
        raise HTTPException(
            status_code=422,
            detail="Provide either contact_id, or both name and email, to add a member.",
        )

    try:
        if payload.contact_id is not None:
            contact_id = payload.contact_id
            repository.get_contact(contact_id)  # 404s early if it doesn't exist
        else:
            contact_id = repository.create_contact(payload.name, payload.email).id

        repository.add_team_member(team_id, contact_id)
        return repository.get_team_with_members(team_id)
    except TeamNotFoundError as exc:
        raise _team_not_found(team_id) from exc
    except ContactNotFoundError as exc:
        raise _contact_not_found(exc.contact_id) from exc


@router.delete("/{team_id}/members/{contact_id}", response_model=TeamWithMembers)
async def remove_team_member(team_id: int, contact_id: int) -> TeamWithMembers:
    repository = get_contacts_repository()
    try:
        repository.remove_team_member(team_id, contact_id)
        return repository.get_team_with_members(team_id)
    except TeamNotFoundError as exc:
        raise _team_not_found(team_id) from exc
    except ContactNotFoundError as exc:
        raise _contact_not_found(exc.contact_id) from exc
    except MembershipNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
