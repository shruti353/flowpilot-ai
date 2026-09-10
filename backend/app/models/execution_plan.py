"""Execution plan schema: the AI's structured, not-yet-executed output.

The Week 2 persistence/approval envelope (StoredPlan, AgentPlanResponse,
etc.) lives in app/models/stored_plan.py, which imports from here - keep
this module free of that dependency to avoid a circular import.
"""

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.models.action import Action

#: Week 5: a plan may contain 1-3 actions. This is a deliberate, deterministic
#: limit - a request that would produce more actions is rejected outright
#: (via the validator below) rather than silently truncated or partially
#: accepted.
MAX_ACTIONS_PER_PLAN = 3


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
    def validate_action_count_and_uniqueness(self) -> "ExecutionPlan":
        if len(self.actions) == 0:
            raise ValueError("An execution plan must contain at least one action.")
        if len(self.actions) > MAX_ACTIONS_PER_PLAN:
            raise ValueError(
                f"This request produced {len(self.actions)} actions, which exceeds the "
                f"maximum of {MAX_ACTIONS_PER_PLAN} actions supported per plan. Please "
                "split it into smaller requests."
            )
        action_ids = [action.action_id for action in self.actions]
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("Each action in a plan must have a unique action_id.")
        return self

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
