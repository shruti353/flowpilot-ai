"""Direct access to deterministic recipient resolution
(app/services/contact_resolution_service.py), independent of the plan
generation pipeline.

Not part of the plan/agent flow - RESOLVE_RECIPIENTS
(app/agent/nodes/resolve_recipients.py) already calls the same function
during plan generation. This endpoint exists so resolution behavior (a
name, a team, or a direct email -> real addresses or a clear reason) can
be inspected/verified on its own, without needing a live LLM call.
"""

from fastapi import APIRouter, Query

from app.services.contact_resolution_service import RecipientResolutionResult, resolve_recipient_reference

router = APIRouter(prefix="/recipients", tags=["recipients"])


@router.get("/resolve", response_model=RecipientResolutionResult)
async def resolve_recipient(
    reference: str = Query(..., min_length=1, description="A name, team name, or email address."),
) -> RecipientResolutionResult:
    return resolve_recipient_reference(reference)
