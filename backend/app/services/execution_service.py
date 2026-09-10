"""Deterministic orchestration for approval-gated execution.

Approving a plan only changes its status (see approval_service.py) - it
never runs anything. This module is what actually runs a plan's actions,
delegating each one to app/execution/executor.py, which picks an adapter via
the dispatcher in app/execution/dispatcher.py. It never talks to the LLM and
never talks to Google Calendar directly.

Duplicate-execution safety: claiming a plan (one of EXECUTABLE_STATUSES ->
executing) is a single atomic compare-and-swap against the repository (see
PlanRepository.compare_and_update). Once claimed, no other request can also
claim it - a second concurrent /execute call always sees a non-executable
status and is rejected before any adapter or n8n call happens.

Idempotent retries: a plan that came back "partially_executed" or
"execution_failed" may be executed again (an "executed" plan may not - every
action already succeeded, there is nothing to retry). On a retry, any action
whose PREVIOUS attempt already succeeded is carried forward as-is and is
NEVER re-dispatched to its adapter - this is what guarantees a retry cannot
create a second Google Calendar event for an action that already created
one. Only actions that previously failed, were unsupported, or have never
been attempted are (re-)executed.
"""

from datetime import datetime, timezone

from app.execution.adapters.base import ExecutionContext
from app.execution.executor import execute_action
from app.execution.result import ActionExecutionResult, ActionExecutionStatus, PlanExecutionResult
from app.models.stored_plan import StoredPlan, StoredPlanStatus
from app.repositories.plan_repository import PlanConflictError, PlanRepository, get_plan_repository
from app.services.approval_service import InvalidPlanTransitionError

#: Statuses a plan may be (re-)executed from. "executed" is deliberately
#: excluded - every action already succeeded, so there is nothing to retry.
EXECUTABLE_STATUSES = frozenset(
    {StoredPlanStatus.approved, StoredPlanStatus.partially_executed, StoredPlanStatus.execution_failed}
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _summarize(action_results: list[ActionExecutionResult]) -> tuple[StoredPlanStatus, str]:
    total = len(action_results)
    succeeded = sum(1 for result in action_results if result.status == ActionExecutionStatus.succeeded)

    if total > 0 and succeeded == total:
        return StoredPlanStatus.executed, "success"
    if succeeded > 0:
        return StoredPlanStatus.partially_executed, "partial"
    return StoredPlanStatus.execution_failed, "failed"


class ExecutionService:
    def __init__(self, repository: PlanRepository | None = None) -> None:
        self._repository = repository or get_plan_repository()

    async def execute_plan(self, plan_id: str, request_id: str) -> StoredPlan:
        plan = self._claim_for_execution(plan_id)

        if plan.execution_plan is None or not plan.execution_plan.actions:
            # Structurally shouldn't happen - only plans that went through
            # ApprovalService.approve() (which requires an execution_plan)
            # ever reach "approved". Handled defensively rather than
            # assumed away.
            empty_result = PlanExecutionResult(status="failed", actions=[])
            return self._repository.update(
                plan.model_copy(
                    update={
                        "status": StoredPlanStatus.execution_failed,
                        "execution": empty_result,
                        "updated_at": _utcnow(),
                    }
                )
            )

        context = ExecutionContext(request_id=request_id, plan_id=plan_id)
        previous_by_action_id = {
            result.action_id: result for result in (plan.execution.actions if plan.execution else [])
        }

        action_results: list[ActionExecutionResult] = []
        for action in plan.execution_plan.actions:
            previous = previous_by_action_id.get(action.action_id)
            if previous is not None and previous.status == ActionExecutionStatus.succeeded:
                # Already succeeded on an earlier attempt - never re-dispatch
                # it, or a retry could create a second real side effect
                # (e.g. a duplicate Google Calendar event).
                action_results.append(previous)
                continue

            result = await execute_action(action, context)
            attempt_count = previous.attempt_count + 1 if previous is not None else 1
            action_results.append(result.model_copy(update={"attempt_count": attempt_count}))

        overall_status, outcome = _summarize(action_results)
        updated = plan.model_copy(
            update={
                "status": overall_status,
                "execution": PlanExecutionResult(status=outcome, actions=action_results),
                "updated_at": _utcnow(),
            }
        )
        return self._repository.update(updated)

    def _claim_for_execution(self, plan_id: str) -> StoredPlan:
        def predicate(plan: StoredPlan) -> bool:
            return plan.status in EXECUTABLE_STATUSES

        def claim(plan: StoredPlan) -> StoredPlan:
            return plan.model_copy(
                update={"status": StoredPlanStatus.executing, "updated_at": _utcnow()}
            )

        try:
            return self._repository.compare_and_update(plan_id, predicate, claim)
        except PlanConflictError as exc:
            allowed = ", ".join(sorted(status.value for status in EXECUTABLE_STATUSES))
            raise InvalidPlanTransitionError(
                plan_id,
                exc.current_status,
                f"Plan '{plan_id}' cannot be executed from status "
                f"'{exc.current_status.value}'. Only plans in one of "
                f"[{allowed}] may be executed.",
            ) from exc


_service = ExecutionService()


def get_execution_service() -> ExecutionService:
    return _service
