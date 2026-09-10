"""ENRICH_DATETIME node: deterministic post-processing of the raw LLM plan.

Runs after INFER_TITLES and before VALIDATE_PLAN, directly on
state["raw_plan"] - the LLM-generated plan is never discarded or
regenerated, only patched in place.

For calendar.create_event specifically, this node is the sole, deterministic
authority on whether a date and/or a time were actually supplied - it never
trusts the LLM's own "date"/"time"/"datetime" parameters or its
missing_information claims for these two fields, because a local model will
happily invent a plausible date (e.g. "tomorrow") even when told not to (see
app/prompts/planner_prompt.py's hard rules). Presence is instead re-derived
straight from the user's own words via
app.utils.datetime_extraction.extract_date_and_time_phrases, and only what
that finds is ever resolved - see _enrich_create_event_datetime below.

Other calendar operations (e.g. get_event) keep the simpler legacy
behavior: resolve a single "datetime" parameter if the LLM supplied one,
never inventing one otherwise.
"""

from typing import Any

from app.agent.state import AgentState
from app.core.config import get_settings
from app.core.logging import get_logger
from app.utils.datetime_extraction import extract_date_and_time_phrases
from app.utils.datetime_parser import DatetimeNormalizationError, normalize_datetime

logger = get_logger(__name__)

#: Parameter keys this module owns for calendar.create_event - always
#: recomputed from scratch, never partially trusted from a prior value.
_OWNED_PARAMETER_KEYS = ("date", "time", "datetime", "resolved_date", "resolved_time", "resolved_datetime")
_OWNED_MISSING_FIELDS = ("date", "time", "datetime")


def resolve_calendar_datetime(parameters: dict[str, Any], timezone_name: str) -> None:
    """Deterministically resolve whatever of parameters["date"] /
    parameters["time"] (or, for calendar operations other than create_event,
    a legacy combined parameters["datetime"]) are already present, in place.

    This only RESOLVES values that are already there - it never invents a
    date or a time. Used both by GENERATE_PLAN's enrichment pipeline (below)
    and by POST /plans/{plan_id}/fields (app/services/plan_update_service.py)
    once the user has supplied date/time values directly via the missing-
    fields form, where there is no free text to re-derive presence from.
    """
    for stale in ("resolved_date", "resolved_time", "resolved_datetime"):
        parameters.pop(stale, None)

    date_value = parameters.get("date")
    time_value = parameters.get("time")

    if date_value and time_value:
        combined = f"{date_value} {time_value}".strip()
        try:
            resolved = normalize_datetime(combined, timezone_name)
        except DatetimeNormalizationError:
            return
        parameters["datetime"] = combined
        parameters["resolved_datetime"] = resolved.isoformat()
        return

    if date_value:
        try:
            resolved = normalize_datetime(str(date_value), timezone_name)
        except DatetimeNormalizationError:
            return
        parameters["resolved_date"] = resolved.date().isoformat()
        return

    if time_value:
        try:
            resolved = normalize_datetime(str(time_value), timezone_name)
        except DatetimeNormalizationError:
            return
        parameters["resolved_time"] = resolved.strftime("%H:%M:%S")
        return

    # Legacy combined "datetime" parameter - calendar.get_event still uses a
    # single free-text expression rather than separate date/time fields.
    legacy_datetime = parameters.get("datetime")
    if isinstance(legacy_datetime, str) and legacy_datetime.strip():
        try:
            resolved = normalize_datetime(legacy_datetime, timezone_name)
        except DatetimeNormalizationError:
            return
        parameters["resolved_datetime"] = resolved.isoformat()


def _enrich_create_event_datetime(action: dict[str, Any], parameters: dict[str, Any], user_text: str) -> None:
    missing = action.get("missing_information")
    if not isinstance(missing, list):
        missing = []
    for stale_field in _OWNED_MISSING_FIELDS:
        if stale_field in missing:
            missing.remove(stale_field)
    for stale_param in _OWNED_PARAMETER_KEYS:
        parameters.pop(stale_param, None)

    date_phrase, time_phrase = extract_date_and_time_phrases(user_text)

    if date_phrase:
        parameters["date"] = date_phrase
    else:
        missing.append("date")

    if time_phrase:
        parameters["time"] = time_phrase
    else:
        missing.append("time")

    resolve_calendar_datetime(parameters, get_settings().flowpilot_timezone)
    action["missing_information"] = missing


def apply_enrich_datetime(raw_plan: dict, user_text: str = "", request_id: str | None = None) -> dict:
    """Pure transform: resolves calendar date/time information in place.

    Extracted so both the LangGraph node below and (for non-create_event
    calendar operations only - create_event always goes through the
    text-driven path above) any other deterministic caller can reuse this
    logic without duplicating it.
    """
    actions = raw_plan.get("actions")
    if not isinstance(actions, list):
        return raw_plan

    settings = get_settings()

    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("tool") != "calendar":
            continue

        parameters = action.setdefault("parameters", {})

        if action.get("operation") == "create_event":
            _enrich_create_event_datetime(action, parameters, user_text)
            continue

        # Other calendar operations (e.g. get_event): legacy behavior -
        # resolve a single "datetime" parameter if the LLM supplied one,
        # never invent one otherwise.
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
                extra={"request_id": request_id},
            )
            continue
        parameters["resolved_datetime"] = resolved.isoformat()

    return raw_plan


def enrich_datetime(state: AgentState) -> AgentState:
    if state.get("errors"):
        return state

    raw_plan = state.get("raw_plan")
    if not isinstance(raw_plan, dict):
        return state

    apply_enrich_datetime(raw_plan, state.get("user_text", ""), state.get("request_id"))
    return state
