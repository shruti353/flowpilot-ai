"""Common interface every execution adapter implements."""

from abc import ABC, abstractmethod

from app.execution.result import ActionExecutionResult
from app.models.action import Action


class ExecutionContext:
    """Everything an adapter needs to execute one action, and nothing
    more - no plan history, no LLM reasoning, no other actions."""

    __slots__ = ("request_id", "plan_id")

    def __init__(self, request_id: str, plan_id: str) -> None:
        self.request_id = request_id
        self.plan_id = plan_id


class ExecutionAdapter(ABC):
    """Transforms one internal Action into a real external effect (or a
    structured failure) and reports back a single ActionExecutionResult.
    An adapter never touches plan/repository state - that's the
    execution service's job.
    """

    @abstractmethod
    async def execute(self, action: Action, context: ExecutionContext) -> ActionExecutionResult:
        ...
