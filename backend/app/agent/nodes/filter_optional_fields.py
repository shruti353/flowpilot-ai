"""FILTER_OPTIONAL_FIELDS node: deterministic post-processing of the raw
LLM plan.

Runs after ENRICH_DATETIME and before VALIDATE_PLAN, directly on
state["raw_plan"] - the LLM-generated plan is never discarded or
regenerated, only patched in place. The planner prompt lists "location" as
a merely "typical" parameter for calendar.create_event (see
app/prompts/planner_prompt.py), not a required one, but the LLM sometimes
adds it to an action's missing_information anyway when the user didn't
mention one. Nothing else in the pipeline distinguishes required from
optional missing fields before ExecutionPlan.derive_status flips the
whole plan to "needs_clarification" on ANY non-empty
missing_information - so an absent, genuinely optional location was
incorrectly blocking approval.

This node removes only the specific optional field names below, per
(tool, operation), from missing_information. It never removes a field
that's actually required (e.g. title, datetime), never invents a value
for the field it drops, and never touches actions for other
tools/operations.
"""

from app.agent.state import AgentState

#: Parameter names allowed to be absent for a given (tool, operation)
#: without blocking the plan on "needs_clarification". Keep this narrowly
#: scoped - only fields the corresponding execution adapter genuinely
#: treats as optional belong here.
OPTIONAL_MISSING_FIELDS: dict[tuple[str, str], frozenset[str]] = {
    ("calendar", "create_event"): frozenset({"location"}),
}


def filter_optional_fields(state: AgentState) -> AgentState:
    if state.get("errors"):
        return state

    raw_plan = state.get("raw_plan")
    if not isinstance(raw_plan, dict):
        return state

    actions = raw_plan.get("actions")
    if not isinstance(actions, list):
        return state

    for action in actions:
        if not isinstance(action, dict):
            continue

        optional_fields = OPTIONAL_MISSING_FIELDS.get((action.get("tool"), action.get("operation")))
        if not optional_fields:
            continue

        missing = action.get("missing_information")
        if not isinstance(missing, list):
            continue

        action["missing_information"] = [field for field in missing if field not in optional_fields]

    return state
