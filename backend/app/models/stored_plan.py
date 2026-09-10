"""Human-in-the-loop plan lifecycle models: persistence + approval state
(Week 2), extended with approval-gated execution state (Week 3).

These wrap the Week 1 `ExecutionPlan`. Storage itself lives in
`app/repositories/plan_repository.py` and is in-memory only - every
StoredPlan is lost when the process restarts.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.execution.result import PlanExecutionResult
from app.models.execution_plan import ExecutionPlan, ValidationErrorDetail


class StoredPlanStatus(str, Enum):
    #: Fully-specified plan, persisted, waiting on a human decision.
    awaiting_approval = "awaiting_approval"
    #: Structurally valid plan, but at least one action is missing required
    #: details. Persisted for visibility, but never approvable as-is.
    needs_clarification = "needs_clarification"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"
    #: The request could not be turned into a valid plan at all (e.g. an
    #: unsupported tool/operation, or an unparseable LLM response).
    error = "error"
    #: Week 3: claimed for execution. Transient - a single synchronous
    #: /execute call moves a plan through this on its way to one of the
    #: three terminal execution outcomes below. No plan should be
    #: observed sitting in "executing" between requests.
    executing = "executing"
    #: Every action executed successfully.
    executed = "executed"
    #: At least one action succeeded, but at least one failed or is
    #: unsupported.
    partially_executed = "partially_executed"
    #: No action succeeded (all failed, all unsupported, or a mix).
    execution_failed = "execution_failed"


#: The only status a plan may be approved/rejected/cancelled from.
PENDING_STATUS = StoredPlanStatus.awaiting_approval

#: Statuses a plan can never execute from - approval was never granted, the
#: decision was final (rejected/cancelled), or every action already
#: succeeded (executed - nothing left to retry). Week 4: partially_executed
#: and execution_failed are deliberately NOT in this set - a plan that
#: didn't fully succeed may be retried via the same /execute endpoint,
#: which only re-attempts actions that didn't already succeed (see
#: app/services/execution_service.py).
NON_EXECUTABLE_STATUSES = frozenset(
    {
        StoredPlanStatus.awaiting_approval,
        StoredPlanStatus.needs_clarification,
        StoredPlanStatus.rejected,
        StoredPlanStatus.cancelled,
        StoredPlanStatus.error,
        StoredPlanStatus.executing,
        StoredPlanStatus.executed,
    }
)


class StoredPlan(BaseModel):
    """A plan persisted by the in-memory repository."""

    plan_id: str
    status: StoredPlanStatus
    execution_plan: ExecutionPlan | None = None
    errors: list[ValidationErrorDetail] | None = None
    rejection_reason: str | None = None
    #: Populated once /execute has been called at least once. None before that.
    execution: PlanExecutionResult | None = None
    created_at: datetime
    updated_at: datetime


class AgentPlanResponse(BaseModel):
    """Response body for POST /api/v1/agent/plan.

    `status` is the STORED plan's lifecycle status: "awaiting_approval" for
    a fully-specified plan, "needs_clarification" if required information
    is missing, or "error" if the request could not be turned into a valid
    plan at all. It never reflects execution - nothing is ever executed.
    """

    request_id: str
    plan_id: str | None = None
    status: StoredPlanStatus
    execution_plan: ExecutionPlan | None = None
    errors: list[ValidationErrorDetail] | None = None


class RejectPlanRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class ActionFieldValues(BaseModel):
    """User-supplied values for one action's currently-missing fields."""

    action_id: str = Field(..., min_length=1)
    values: dict[str, Any] = Field(..., min_length=1)


class UpdatePlanFieldsRequest(BaseModel):
    actions: list[ActionFieldValues] = Field(..., min_length=1)


class UpdatePlanFieldsResponse(BaseModel):
    plan_id: str
    status: StoredPlanStatus
    message: str
    plan: StoredPlan


class ApprovePlanResponse(BaseModel):
    plan_id: str
    status: StoredPlanStatus
    message: str
    plan: StoredPlan


class RejectPlanResponse(BaseModel):
    plan_id: str
    status: StoredPlanStatus
    message: str
    rejection_reason: str | None = None
    plan: StoredPlan


class CancelPlanResponse(BaseModel):
    plan_id: str
    status: StoredPlanStatus
    message: str
    plan: StoredPlan


class ExecutePlanResponse(BaseModel):
    """Response body for POST /api/v1/plans/{plan_id}/execute.

    `status` is one of "executed", "partially_executed", or
    "execution_failed" - the endpoint never returns without having
    reached one of these three terminal outcomes.
    """

    plan_id: str
    status: StoredPlanStatus
    message: str
    execution: PlanExecutionResult | None = None
    plan: StoredPlan


class PlanErrorDetail(BaseModel):
    """Structured error payload for 404 / 409 responses on plan endpoints."""

    plan_id: str
    message: str
    current_status: StoredPlanStatus | None = None
