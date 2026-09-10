"""Minimal CRUD for the Contacts store (see app/repositories/contacts_repository.py).

This is what makes "save a contact for future use" concretely usable today
- deterministic recipient resolution (app/services/contact_resolution_service.py)
reads from the same store, never the LLM.
"""

from fastapi import APIRouter, HTTPException

from app.models.contact import Contact, CreateContactRequest, UpdateContactRequest
from app.repositories.contacts_repository import (
    ContactNotFoundError,
    DuplicateEmailError,
    get_contacts_repository,
)

router = APIRouter(prefix="/contacts", tags=["contacts"])


def _not_found(contact_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No contact found with id {contact_id}.")


@router.post("", response_model=Contact)
async def create_contact(payload: CreateContactRequest) -> Contact:
    return get_contacts_repository().create_contact(payload.name, payload.email)


@router.get("", response_model=list[Contact])
async def list_contacts() -> list[Contact]:
    return get_contacts_repository().list_contacts()


@router.get("/{contact_id}", response_model=Contact)
async def get_contact(contact_id: int) -> Contact:
    try:
        return get_contacts_repository().get_contact(contact_id)
    except ContactNotFoundError as exc:
        raise _not_found(contact_id) from exc


@router.patch("/{contact_id}", response_model=Contact)
async def update_contact(contact_id: int, payload: UpdateContactRequest) -> Contact:
    try:
        return get_contacts_repository().update_contact(
            contact_id, name=payload.name, email=payload.email
        )
    except ContactNotFoundError as exc:
        raise _not_found(contact_id) from exc
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{contact_id}", status_code=204)
async def delete_contact(contact_id: int) -> None:
    try:
        get_contacts_repository().delete_contact(contact_id)
    except ContactNotFoundError as exc:
        raise _not_found(contact_id) from exc
