"""Deterministic application logic for the plan approval lifecycle.

Nothing here calls the LLM or LangGraph - approving, rejecting, and
cancelling a plan are pure state-machine transitions over a stored plan.
Planning (the AI's job) and approval (a human's job) are kept strictly
separate: this module never executes anything either.
"""

import uuid
from datetime import datetime, timezone

from app.models.execution_plan import ExecutionPlan, ValidationErrorDetail
from app.models.stored_plan import PENDING_STATUS, StoredPlan, StoredPlanStatus
from app.repositories.plan_repository import PlanRepository, get_plan_repository


class InvalidPlanTransitionError(Exception):
    """Raised when a plan is not in a state that allows the requested transition."""

    def __init__(self, plan_id: str, current_status: StoredPlanStatus, message: str) -> None:
        self.plan_id = plan_id
        self.current_status = current_status
        self.message = message
        super().__init__(message)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalService:
    def __init__(self, repository: PlanRepository | None = None) -> None:
        self._repository = repository or get_plan_repository()

    def store_new_plan(
        self,
        execution_plan: ExecutionPlan | None,
        errors: list[ValidationErrorDetail] | None,
    ) -> StoredPlan:
        """Persist the outcome of a GENERATE_PLAN/VALIDATE_PLAN run.

        A structurally valid plan becomes "awaiting_approval" (or
        "needs_clarification" if it has missing required information). A
        plan that failed Pydantic validation (unsupported tool/operation,
        unparseable LLM output, ...) is still stored - with no
        execution_plan and status "error" - so it has a plan_id and is
        visible/traceable, even though it can never be approved.
        """
        if execution_plan is not None:
            status = (
                StoredPlanStatus.needs_clarification
                if execution_plan.status.value == "needs_clarification"
                else StoredPlanStatus.awaiting_approval
            )
            plan_id = execution_plan.plan_id
        else:
            status = StoredPlanStatus.error
            plan_id = str(uuid.uuid4())

        now = _utcnow()
        plan = StoredPlan(
            plan_id=plan_id,
            status=status,
            execution_plan=execution_plan,
            errors=errors,
            created_at=now,
            updated_at=now,
        )
        return self._repository.add(plan)

    def get_plan(self, plan_id: str) -> StoredPlan:
        return self._repository.get(plan_id)

    def _require_pending(self, plan_id: str, action: str) -> StoredPlan:
        plan = self._repository.get(plan_id)
        if plan.status != PENDING_STATUS:
            raise InvalidPlanTransitionError(
                plan_id,
                plan.status,
                f"Plan '{plan_id}' cannot be {action} from status "
                f"'{plan.status.value}'. Only plans in "
                f"'{PENDING_STATUS.value}' may be {action}.",
            )
        return plan

    def approve(self, plan_id: str) -> StoredPlan:
        plan = self._require_pending(plan_id, "approved")

        if plan.execution_plan is not None and any(
            action.missing_information for action in plan.execution_plan.actions
        ):
            raise InvalidPlanTransitionError(
                plan_id,
                plan.status,
                f"Plan '{plan_id}' has actions missing required information "
                "and cannot be approved.",
            )

        updated = plan.model_copy(
            update={"status": StoredPlanStatus.approved, "updated_at": _utcnow()}
        )
        return self._repository.update(updated)

    def reject(self, plan_id: str, reason: str | None) -> StoredPlan:
        plan = self._require_pending(plan_id, "rejected")
        updated = plan.model_copy(
            update={
                "status": StoredPlanStatus.rejected,
                "rejection_reason": reason,
                "updated_at": _utcnow(),
            }
        )
        return self._repository.update(updated)

    def cancel(self, plan_id: str) -> StoredPlan:
        plan = self._require_pending(plan_id, "cancelled")
        updated = plan.model_copy(
            update={"status": StoredPlanStatus.cancelled, "updated_at": _utcnow()}
        )
        return self._repository.update(updated)


_service = ApprovalService()


def get_approval_service() -> ApprovalService:
    return _service
