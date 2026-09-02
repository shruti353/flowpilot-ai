"""ENRICH_DATETIME node: deterministic post-processing of the raw LLM plan.

Runs after INFER_TITLES and before VALIDATE_PLAN, directly on
state["raw_plan"] - the LLM-generated plan is never discarded or
regenerated, only patched in place. For any calendar action with a
"datetime" parameter, this resolves the (possibly relative) expression
into a concrete, timezone-aware ISO 8601 string via
app.utils.datetime_parser.normalize_datetime - the same deterministic
parser the n8n calendar adapter already uses at execution time - and
stores it as "resolved_datetime" alongside the untouched original
expression. It never invents a datetime when none was provided, and never
touches non-calendar actions or other parameters (location included).
"""

from app.agent.state import AgentState
from app.core.config import get_settings
from app.core.logging import get_logger
from app.utils.datetime_parser import DatetimeNormalizationError, normalize_datetime

logger = get_logger(__name__)


def enrich_datetime(state: AgentState) -> AgentState:
    if state.get("errors"):
        return state

    raw_plan = state.get("raw_plan")
    if not isinstance(raw_plan, dict):
        return state

    actions = raw_plan.get("actions")
    if not isinstance(actions, list):
        return state

    settings = get_settings()

    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("tool") != "calendar":
            continue

        parameters = action.setdefault("parameters", {})
        if parameters.get("resolved_datetime"):
            continue

        raw_datetime = parameters.get("datetime")
        if not isinstance(raw_datetime, str) or not raw_datetime.strip():
            continue

        try:
            resolved = normalize_datetime(raw_datetime, settings.flowpilot_timezone)
        except DatetimeNormalizationError as exc:
            logger.warning(
                "datetime enrichment failed for action %s: %s",
                action.get("action_id"),
                exc.message,
                extra={"request_id": state.get("request_id")},
            )
            continue

        parameters["resolved_datetime"] = resolved.isoformat()

    return state
