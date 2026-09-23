"""Structured results for executing one action, and for a whole plan's
execution attempt. These are the ONLY shapes execution ever produces -
success or a named failure reason, never a guess."""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

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


#: Which pipeline stage a given error code originates from, for downstream
#: error transparency (e.g. so the frontend can distinguish "you're missing
#: a parameter" from "n8n itself is unreachable"). Codes not listed here
#: (n8n-reported failure codes like CALENDAR_API_ERROR, or the generic
#: N8N_EXECUTION_FAILED fallback) default to "workflow" - n8n ran and told
#: us it failed.
_STAGE_BY_CODE: dict[str, str] = {
    "MISSING_PARAMETERS": "validation",
    "DATETIME_NORMALIZATION_FAILED": "validation",
    "UNRESOLVED_RECIPIENTS": "validation",
    "N8N_NOT_CONFIGURED": "configuration",
    "N8N_TIMEOUT": "transport",
    "N8N_UNREACHABLE": "transport",
    "N8N_HTTP_ERROR": "transport",
    "N8N_INVALID_RESPONSE": "transport",
    "EXECUTION_NOT_SUPPORTED": "unsupported",
}
_DEFAULT_STAGE = "workflow"

ErrorStage = Literal["validation", "configuration", "transport", "workflow", "unsupported"]


class ExecutionErrorDetail(BaseModel):
    code: str
    message: str
    #: Derived deterministically from `code` - never set directly by callers,
    #: the same pattern Action.missing_fields uses for missing_information.
    stage: ErrorStage = _DEFAULT_STAGE  # type: ignore[assignment]

    @model_validator(mode="after")
    def derive_stage(self) -> "ExecutionErrorDetail":
        self.stage = _STAGE_BY_CODE.get(self.code, _DEFAULT_STAGE)  # type: ignore[assignment]
        return self


class ActionExecutionResult(BaseModel):
    action_id: str
    tool: ToolName
    operation: OperationName
    status: ActionExecutionStatus
    result: dict[str, Any] | None = None
    error: ExecutionErrorDetail | None = None
    #: How many times execution has been attempted for this action across
    #: retries of the same plan. Held at its prior value (never
    #: incremented) when a previously-succeeded result is carried forward
    #: without being re-attempted.
    attempt_count: int = Field(default=1, ge=1)


class PlanExecutionResult(BaseModel):
    """Summary of one execute-plan attempt, mirrored at `StoredPlan.execution`."""

    #: "success" = every action succeeded, "partial" = some but not all,
    #: "failed" = none did (including "everything was unsupported").
    status: Literal["success", "partial", "failed"]
    actions: list[ActionExecutionResult]
