"""Shared, reusable "turn a raw plan dict into a validated ExecutionPlan (or
structured errors)" logic.

Originally lived only inside the VALIDATE_PLAN LangGraph node
(app/agent/nodes/validate.py). Extracted here so POST /plans/{plan_id}/fields
(app/services/plan_update_service.py) can revalidate a plan after the user
fills in missing fields using the exact same rules - never a second,
diverging implementation of "what makes a plan valid".
"""

import uuid

from pydantic import ValidationError

from app.models.execution_plan import ExecutionPlan, ValidationErrorDetail


def validate_raw_plan(
    raw_plan: object, *, plan_id: str | None = None
) -> tuple[ExecutionPlan | None, list[ValidationErrorDetail]]:
    """Construct an ExecutionPlan from a raw dict, or return validation errors.

    `plan_id` lets a caller revalidating an *existing* plan keep its id
    instead of minting a new one (new plan generation always mints a fresh
    id; updating an existing plan's fields must not change it).
    """
    if not isinstance(raw_plan, dict):
        return None, [
            ValidationErrorDetail(
                loc="raw_plan",
                message="The LLM response was not a JSON object matching the execution plan schema.",
            )
        ]

    plan_data = {**raw_plan, "plan_id": plan_id or str(uuid.uuid4())}

    try:
        return ExecutionPlan(**plan_data), []
    except ValidationError as exc:
        errors = [
            ValidationErrorDetail(
                loc=".".join(str(part) for part in error["loc"]) or "plan",
                message=error["msg"],
            )
            for error in exc.errors()
        ]
        return None, errors
