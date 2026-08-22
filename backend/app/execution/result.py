"""Structured results for executing one action, and for a whole plan's
execution attempt. These are the ONLY shapes execution ever produces -
success or a named failure reason, never a guess."""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel

from app.models.action import OperationName, ToolName


class ActionExecutionStatus(str, Enum):
    pending = "pending"
    executing = "executing"
    succeeded = "succeeded"
    failed = "failed"
    #: Reserved for a future case where an action is deliberately not
    #: attempted (e.g. depends on a prior failed action). Unused today.
    skipped = "skipped"
    #: No execution adapter exists yet for this tool/operation.
    unsupported = "unsupported"


class ExecutionErrorDetail(BaseModel):
    code: str
    message: str


class ActionExecutionResult(BaseModel):
    action_id: str
    tool: ToolName
    operation: OperationName
    status: ActionExecutionStatus
    result: dict[str, Any] | None = None
    error: ExecutionErrorDetail | None = None


class PlanExecutionResult(BaseModel):
    """Summary of one execute-plan attempt, mirrored at `StoredPlan.execution`."""

    #: "success" = every action succeeded, "partial" = some but not all,
    #: "failed" = none did (including "everything was unsupported").
    status: Literal["success", "partial", "failed"]
    actions: list[ActionExecutionResult]
