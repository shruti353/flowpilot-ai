"""POST /api/v1/agent/plan"""

from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.agent.graph import run_agent_graph
from app.core.logging import get_logger
from app.models.execution_plan import AgentPlanResponse, ValidationErrorDetail
from app.models.request import AgentPlanRequest

router = APIRouter(prefix="/agent", tags=["agent"])
logger = get_logger(__name__)


@router.post("/plan", response_model=AgentPlanResponse)
async def create_plan(payload: AgentPlanRequest) -> AgentPlanResponse:
    request_id = str(uuid4())
    logger.info("agent plan request received", extra={"request_id": request_id})
    logger.info("graph execution started", extra={"request_id": request_id})

    final_state = await run_agent_graph(user_text=payload.text, request_id=request_id)
    status = final_state.get("status")

    if status == "validated" and final_state.get("execution_plan") is not None:
        logger.info("plan validated successfully", extra={"request_id": request_id})
        return AgentPlanResponse(
            request_id=request_id,
            status="success",
            execution_plan=final_state["execution_plan"],
        )

    if status == "llm_error":
        message = (final_state.get("errors") or ["The LLM provider is unavailable."])[-1]
        logger.error("LLM provider error: %s", message, extra={"request_id": request_id})
        raise HTTPException(
            status_code=502,
            detail={"request_id": request_id, "message": message},
        )

    validation_errors = final_state.get("validation_errors") or [
        ValidationErrorDetail(loc="agent", message=message)
        for message in (final_state.get("errors") or ["Unable to generate an execution plan."])
    ]
    logger.warning(
        "plan generation failed with %d error(s)",
        len(validation_errors),
        extra={"request_id": request_id},
    )
    return AgentPlanResponse(request_id=request_id, status="error", errors=validation_errors)
