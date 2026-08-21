"""Execution plan schema: the AI's structured, not-yet-executed output.

The Week 2 persistence/approval envelope (StoredPlan, AgentPlanResponse,
etc.) lives in app/models/stored_plan.py, which imports from here - keep
this module free of that dependency to avoid a circular import.
"""

from enum import Enum

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
