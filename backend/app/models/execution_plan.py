"""Execution plan schema and the top-level API response envelope."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.action import Action


class PlanStatus(str, Enum):
    #: Every action has all the information it needs; still requires human approval to run.
    ready = "ready"
    #: The plan is structurally valid but at least one action is missing required details.
    needs_clarification = "needs_clarification"


class ExecutionPlan(BaseModel):
    """A validated, structured, NOT-YET-EXECUTED plan derived from user text."""

    plan_id: str
    intent: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    actions: list[Action] = Field(default_factory=list)
    status: PlanStatus = PlanStatus.ready

    @model_validator(mode="after")
    def derive_status(self) -> "ExecutionPlan":
        if any(action.missing_information for action in self.actions):
            self.status = PlanStatus.needs_clarification
        else:
            self.status = PlanStatus.ready
        return self


class ValidationErrorDetail(BaseModel):
    """One structured problem found while turning the LLM output into a plan."""

    loc: str = Field(..., description="Dotted path to the offending field, e.g. 'actions.0.tool'.")
    message: str


class AgentPlanResponse(BaseModel):
    """Response body for POST /api/v1/agent/plan."""

    request_id: str
    status: Literal["success", "error"]
    execution_plan: ExecutionPlan | None = None
    errors: list[ValidationErrorDetail] | None = None
