"""RESOLVE_RECIPIENTS node: deterministic post-processing of the raw LLM plan.

Runs after ENRICH_DATETIME and before FILTER_OPTIONAL_FIELDS, directly on
state["raw_plan"] - the LLM-generated plan is never discarded or
regenerated, only patched in place. For every email action with a "to"
parameter, resolves that reference (a name, team name, or email address)
against the persistent Contacts/Teams store via
app.services.contact_resolution_service.resolve_recipient_reference - the
LLM's own "to" text is trusted only as a REFERENCE to resolve, never as an
actual address. On success, sets parameters["resolved_recipients"] and
clears "to" from missing_information; on failure, ensures "to" is listed
as missing and records why in missing_field_hints so the UI can show a
specific reason rather than a bare "missing" prompt.

Never touches non-email actions, and never invents a recipient when "to"
was never given at all - that stays whatever the LLM itself already
reported as missing/present, exactly like other free-text fields
(subject, body, title). Unlike ENRICH_DATETIME, this module does not need
to guard against the LLM inventing a plausible-but-wrong value out of thin
air (a made-up name isn't the failure mode here) - the risk this guards
against is trusting the LLM to invent the *address*, which never happens
because an address only ever comes from resolve_recipient_reference.
"""

from app.agent.state import AgentState
from app.core.logging import get_logger
from app.services.contact_resolution_service import resolve_recipient_reference

logger = get_logger(__name__)


def apply_resolve_recipients(raw_plan: dict, request_id: str | None = None) -> dict:
    """Pure transform: resolves each email action's "to" reference in place.

    Extracted (matching the app/agent/nodes/enrich_datetime.py pattern) so
    both the LangGraph node below and any other deterministic caller can
    reuse this logic without duplicating it.
    """
    actions = raw_plan.get("actions")
    if not isinstance(actions, list):
        return raw_plan

    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("tool") != "email":
            continue

        parameters = action.setdefault("parameters", {})
        to_value = parameters.get("to")
        if not isinstance(to_value, str) or not to_value.strip():
            continue

        missing = action.get("missing_information")
        if not isinstance(missing, list):
            missing = []
        hints = action.get("missing_field_hints")
        if not isinstance(hints, dict):
            hints = {}

        result = resolve_recipient_reference(to_value)

        if result.resolved:
            parameters["resolved_recipients"] = [r.model_dump() for r in result.recipients]
            if "to" in missing:
                missing.remove("to")
            hints.pop("to", None)
        else:
            parameters.pop("resolved_recipients", None)
            if "to" not in missing:
                missing.append("to")
            hints["to"] = result.reason

        action["missing_information"] = missing
        action["missing_field_hints"] = hints

        # Never log the reference text or any resolved address - only
        # whether resolution succeeded, for the same reason contact data
        # is never logged elsewhere in this codebase.
        logger.info(
            "recipient reference %s for action %s",
            "resolved" if result.resolved else "could not be resolved",
            action.get("action_id"),
            extra={"request_id": request_id},
        )

    return raw_plan


def resolve_recipients(state: AgentState) -> AgentState:
    if state.get("errors"):
        return state

    raw_plan = state.get("raw_plan")
    if not isinstance(raw_plan, dict):
        return state

    apply_resolve_recipients(raw_plan, state.get("request_id"))
    return state
