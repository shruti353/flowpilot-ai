"""Explicit, typed state passed between LangGraph nodes."""

from typing import Any, TypedDict

from app.models.execution_plan import ExecutionPlan, ValidationErrorDetail


class AgentState(TypedDict, total=False):
    request_id: str
    user_text: str

    intent: str | None
    raw_plan: Any | None

    execution_plan: ExecutionPlan | None
    validation_errors: list[ValidationErrorDetail]

    #: One of: started, understood, plan_generated, llm_error, validated,
    #: validation_failed, failed.
    status: str
    errors: list[str]


def initial_state(request_id: str, user_text: str) -> AgentState:
    return AgentState(
        request_id=request_id,
        user_text=user_text,
        intent=None,
        raw_plan=None,
        execution_plan=None,
        validation_errors=[],
        status="started",
        errors=[],
    )
