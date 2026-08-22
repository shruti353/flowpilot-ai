"""Chooses an execution adapter for a given (tool, operation) pair.

This registry is the ONLY place that decides what is/isn't really
executable. Adding real execution for a new tool/operation later means
registering an adapter here - never touching the API routes or the
LangGraph planning pipeline.
"""

from app.execution.adapters.base import ExecutionAdapter
from app.execution.adapters.n8n_calendar import N8nCalendarCreateEventAdapter
from app.models.action import OperationName, ToolName

_REGISTRY: dict[tuple[ToolName, OperationName], ExecutionAdapter] = {}


def register_adapter(tool: ToolName, operation: OperationName, adapter: ExecutionAdapter) -> None:
    _REGISTRY[(tool, operation)] = adapter


def get_adapter(tool: ToolName, operation: OperationName) -> ExecutionAdapter | None:
    return _REGISTRY.get((tool, operation))


# Week 3 scope: real execution exists only for calendar.create_event.
# Every other tool/operation intentionally has no adapter and is reported
# as EXECUTION_NOT_SUPPORTED - see app/execution/executor.py.
register_adapter(ToolName.calendar, OperationName.create_event, N8nCalendarCreateEventAdapter())
