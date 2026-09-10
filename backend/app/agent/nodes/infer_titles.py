"""INFER_TITLES node: deterministic post-processing of the raw LLM plan.

Runs after GENERATE_PLAN and before VALIDATE_PLAN, directly on
state["raw_plan"] - the LLM-generated plan is never discarded or
regenerated, only patched in place. For calendar.create_event actions
missing a title, this fills it in via
app.agent.title_inference.infer_meeting_title and removes "title" from
that action's missing_information. It never touches any other
tool/operation, and never invents a title when the deterministic inference
can't derive one - the LLM's own missing_information stands in that case.
"""

from app.agent.state import AgentState
from app.agent.title_inference import infer_meeting_title
from app.core.logging import get_logger

logger = get_logger(__name__)


def apply_infer_titles(raw_plan: dict, user_text: str, request_id: str | None = None) -> dict:
    """Pure transform: fills in an inferable calendar event title in place.

    Extracted so both the LangGraph node below and the deterministic
    plan-update pipeline (used by POST /plans/{plan_id}/fields) can re-run
    exactly this logic without duplicating it.
    """
    actions = raw_plan.get("actions")
    if not isinstance(actions, list):
        return raw_plan

    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("tool") != "calendar" or action.get("operation") != "create_event":
            continue

        parameters = action.setdefault("parameters", {})
        if parameters.get("title"):
            continue

        inferred_title = infer_meeting_title(user_text)
        if inferred_title is None:
            continue

        parameters["title"] = inferred_title

        missing = action.get("missing_information")
        if isinstance(missing, list) and "title" in missing:
            missing.remove("title")

        logger.info(
            "inferred calendar event title deterministically",
            extra={"request_id": request_id},
        )

    return raw_plan


def infer_titles(state: AgentState) -> AgentState:
    if state.get("errors"):
        return state

    raw_plan = state.get("raw_plan")
    if not isinstance(raw_plan, dict):
        return state

    apply_infer_titles(raw_plan, state.get("user_text", ""), state.get("request_id"))
    return state
