"""Action schema: a single logical operation inside an execution plan.

Week 1 only recognizes a fixed set of logical tools/operations. Nothing here
performs a real external call - `tool` and `operation` are just labels the
execution layer (built in a later phase) will eventually act on.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ToolName(str, Enum):
    calendar = "calendar"
    tasks = "tasks"
    email = "email"


class OperationName(str, Enum):
    create_event = "create_event"
    get_event = "get_event"
    create_task = "create_task"
    get_task = "get_task"
    draft_email = "draft_email"
    send_email = "send_email"
    search_email = "search_email"


# Which operations are valid for each tool. Used to reject combinations like
# tool=calendar / operation=send_email with a clear, structured error instead
# of silently accepting them.
TOOL_OPERATIONS: dict[ToolName, frozenset[OperationName]] = {
    ToolName.calendar: frozenset({OperationName.create_event, OperationName.get_event}),
    ToolName.tasks: frozenset({OperationName.create_task, OperationName.get_task}),
    ToolName.email: frozenset(
        {OperationName.draft_email, OperationName.send_email, OperationName.search_email}
    ),
}


class Action(BaseModel):
    """One planned, not-yet-executed operation."""

    action_id: str = Field(..., min_length=1)
    tool: ToolName
    operation: OperationName
    parameters: dict[str, Any] = Field(default_factory=dict)
    missing_information: list[str] = Field(
        default_factory=list,
        description=(
            "Names of required parameters that could not be determined from the "
            "user's request. Populated instead of inventing a value."
        ),
    )
    requires_approval: bool = Field(
        default=True,
        description="Week 1 never executes actions; this is always expected to be true.",
    )

    @model_validator(mode="after")
    def operation_must_be_supported_by_tool(self) -> "Action":
        allowed = TOOL_OPERATIONS.get(self.tool, frozenset())
        if self.operation not in allowed:
            supported = ", ".join(sorted(op.value for op in allowed))
            raise ValueError(
                f"operation '{self.operation.value}' is not supported for tool "
                f"'{self.tool.value}'. Supported operations for this tool: {supported}"
            )
        return self
