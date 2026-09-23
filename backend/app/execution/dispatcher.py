"""Chooses an execution adapter for a given (tool, operation) pair.

This registry is the ONLY place that decides what is/isn't really
executable. Adding real execution for a new tool/operation later means
registering an adapter here - never touching the API routes or the
LangGraph planning pipeline.
"""

from app.execution.adapters.base import ExecutionAdapter
from app.execution.adapters.n8n_calendar import N8nCalendarCreateEventAdapter
from app.execution.adapters.n8n_email import N8nEmailSendAdapter
from app.models.action import OperationName, ToolName

_REGISTRY: dict[tuple[ToolName, OperationName], ExecutionAdapter] = {}


def register_adapter(tool: ToolName, operation: OperationName, adapter: ExecutionAdapter) -> None:
    _REGISTRY[(tool, operation)] = adapter


def get_adapter(tool: ToolName, operation: OperationName) -> ExecutionAdapter | None:
    return _REGISTRY.get((tool, operation))


# Week 3 scope: real execution exists only for calendar.create_event.
# Week 5 Day 5: real execution also exists for email.send_email.
# Every other tool/operation intentionally has no adapter and is reported
# as EXECUTION_NOT_SUPPORTED - see app/execution/executor.py. In particular,
# email.draft_email is NOT registered here - a "draft" is never silently
# promoted to a real send.
register_adapter(ToolName.calendar, OperationName.create_event, N8nCalendarCreateEventAdapter())
register_adapter(ToolName.email, OperationName.send_email, N8nEmailSendAdapter())
