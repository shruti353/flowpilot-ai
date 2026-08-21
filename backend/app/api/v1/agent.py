"""POST /api/v1/agent/plan

Generates a structured plan (LangGraph + Ollama, unchanged from Week 1),
then hands the outcome to the approval service so it becomes a persisted,
human-decidable plan. This endpoint never executes anything and never
decides approval itself - it only ever produces "awaiting_approval",
"needs_clarification", or "error".
"""

from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.agent.graph import run_agent_graph
from app.core.logging import get_logger
from app.models.execution_plan import ValidationErrorDetail
from app.models.request import AgentPlanRequest
from app.models.stored_plan import AgentPlanResponse
from app.services.approval_service import get_approval_service

router = APIRouter(prefix="/agent", tags=["agent"])
logger = get_logger(__name__)


@router.post("/plan", response_model=AgentPlanResponse)
async def create_plan(payload: AgentPlanRequest) -> AgentPlanResponse:
    request_id = str(uuid4())
    logger.info("agent plan request received", extra={"request_id": request_id})
    logger.info("graph execution started", extra={"request_id": request_id})

    final_state = await run_agent_graph(user_text=payload.text, request_id=request_id)
    status = final_state.get("status")

    if status == "llm_error":
        message = (final_state.get("errors") or ["The LLM provider is unavailable."])[-1]
        logger.error("LLM provider error: %s", message, extra={"request_id": request_id})
        raise HTTPException(
            status_code=502,
            detail={"request_id": request_id, "message": message},
        )

    execution_plan = final_state.get("execution_plan") if status == "validated" else None
    validation_errors = final_state.get("validation_errors") or None
    if execution_plan is None and not validation_errors:
        validation_errors = [
            ValidationErrorDetail(loc="agent", message=message)
            for message in (final_state.get("errors") or ["Unable to generate an execution plan."])
        ]

    stored_plan = get_approval_service().store_new_plan(
        execution_plan=execution_plan, errors=validation_errors
    )

    if execution_plan is not None:
        logger.info(
            "plan stored with status '%s'",
            stored_plan.status.value,
            extra={"request_id": request_id},
        )
    else:
        logger.warning(
            "plan generation failed with %d error(s); stored as 'error'",
            len(validation_errors or []),
            extra={"request_id": request_id},
        )

    return AgentPlanResponse(
        request_id=request_id,
        plan_id=stored_plan.plan_id,
        status=stored_plan.status,
        execution_plan=stored_plan.execution_plan,
        errors=stored_plan.errors,
    )
