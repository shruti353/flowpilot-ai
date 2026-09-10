"""VALIDATE_PLAN node: turn the raw LLM output into a validated ExecutionPlan
or a structured list of validation errors. The LLM output is never trusted
as-is.
"""

from app.agent.state import AgentState
from app.core.logging import get_logger
from app.services.plan_validation import validate_raw_plan

logger = get_logger(__name__)


def validate_plan(state: AgentState) -> AgentState:
    if state.get("errors"):
        # Preserve whatever terminal status an earlier node already set
        # (e.g. "llm_error") instead of overwriting it.
        return state

    logger.info("node started: VALIDATE_PLAN", extra={"request_id": state["request_id"]})

    execution_plan, validation_errors = validate_raw_plan(state.get("raw_plan"))

    if execution_plan is None:
        state["validation_errors"] = validation_errors
        state["status"] = "validation_failed"
        logger.warning(
            "plan failed validation with %d error(s)",
            len(validation_errors),
            extra={"request_id": state["request_id"]},
        )
        return state

    state["execution_plan"] = execution_plan
    state["status"] = "validated"

    logger.info("node completed: VALIDATE_PLAN", extra={"request_id": state["request_id"]})
    return state
