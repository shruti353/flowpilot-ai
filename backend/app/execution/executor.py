"""Executes a single action: finds an adapter via the dispatcher and runs
it, or reports EXECUTION_NOT_SUPPORTED if none is registered.

This module has no notion of a "plan" or "approval" - that orchestration
lives in app/services/execution_service.py. Keeping this layer this thin
is what makes "unsupported actions are never sent to any adapter" true by
construction rather than by convention.
"""

from app.execution.adapters.base import ExecutionContext
from app.execution.dispatcher import get_adapter
from app.execution.result import ActionExecutionResult, ActionExecutionStatus, ExecutionErrorDetail
from app.models.action import Action


async def execute_action(action: Action, context: ExecutionContext) -> ActionExecutionResult:
    adapter = get_adapter(action.tool, action.operation)
    if adapter is None:
        return ActionExecutionResult(
            action_id=action.action_id,
            tool=action.tool,
            operation=action.operation,
            status=ActionExecutionStatus.unsupported,
            error=ExecutionErrorDetail(
                code="EXECUTION_NOT_SUPPORTED",
                message=(
                    f"Execution is not implemented for {action.tool.value}."
                    f"{action.operation.value}."
                ),
            ),
        )
    return await adapter.execute(action, context)
