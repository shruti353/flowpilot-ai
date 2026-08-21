"""VALIDATE_PLAN node: turn the raw LLM output into a validated ExecutionPlan
or a structured list of validation errors. The LLM output is never trusted
as-is.
"""

import uuid

from pydantic import ValidationError

from app.agent.state import AgentState
from app.core.logging import get_logger
from app.models.execution_plan import ExecutionPlan, ValidationErrorDetail

logger = get_logger(__name__)


def validate_plan(state: AgentState) -> AgentState:
    if state.get("errors"):
        # Preserve whatever terminal status an earlier node already set
        # (e.g. "llm_error") instead of overwriting it.
        return state

    logger.info("node started: VALIDATE_PLAN", extra={"request_id": state["request_id"]})

    raw_plan = state.get("raw_plan")
    if not isinstance(raw_plan, dict):
        state["validation_errors"] = [
            ValidationErrorDetail(
                loc="raw_plan",
                message="The LLM response was not a JSON object matching the execution plan schema.",
            )
        ]
        state["status"] = "validation_failed"
        return state

    plan_data = {**raw_plan, "plan_id": str(uuid.uuid4())}

    try:
        execution_plan = ExecutionPlan(**plan_data)
    except ValidationError as exc:
        state["validation_errors"] = [
            ValidationErrorDetail(
                loc=".".join(str(part) for part in error["loc"]) or "plan",
                message=error["msg"],
            )
            for error in exc.errors()
        ]
        state["status"] = "validation_failed"
        logger.warning(
            "plan failed validation with %d error(s)",
            len(state["validation_errors"]),
            extra={"request_id": state["request_id"]},
        )
        return state

    state["execution_plan"] = execution_plan
    state["status"] = "validated"

    logger.info("node completed: VALIDATE_PLAN", extra={"request_id": state["request_id"]})
    return state
