"""In-memory plan repository.

IMPORTANT: storage is entirely in-process memory (a plain dict behind a
lock). There is no database - every stored plan is lost the moment the
application process restarts. This is intentional for this phase; a
durable store is future work.
"""

import threading
from typing import Callable

from app.models.stored_plan import StoredPlan, StoredPlanStatus


class PlanNotFoundError(Exception):
    def __init__(self, plan_id: str) -> None:
        self.plan_id = plan_id
        super().__init__(f"No plan found with plan_id '{plan_id}'.")


class PlanConflictError(Exception):
    """Raised by `compare_and_update` when a plan's current status doesn't
    satisfy the caller's predicate - e.g. trying to claim a plan for
    execution that isn't `approved`. Kept generic (repository-level) on
    purpose; callers translate it into their own domain error."""

    def __init__(self, plan_id: str, current_status: StoredPlanStatus) -> None:
        self.plan_id = plan_id
        self.current_status = current_status
        super().__init__(
            f"Plan '{plan_id}' is not in a state that allows this operation "
            f"(current status: '{current_status.value}')."
        )


class PlanRepository:
    """Thread-safe in-memory store of StoredPlan records, keyed by plan_id."""

    def __init__(self) -> None:
        self._plans: dict[str, StoredPlan] = {}
        self._lock = threading.Lock()

    def add(self, plan: StoredPlan) -> StoredPlan:
        with self._lock:
            self._plans[plan.plan_id] = plan
        return plan

    def get(self, plan_id: str) -> StoredPlan:
        with self._lock:
            plan = self._plans.get(plan_id)
        if plan is None:
            raise PlanNotFoundError(plan_id)
        return plan

    def update(self, plan: StoredPlan) -> StoredPlan:
        with self._lock:
            if plan.plan_id not in self._plans:
                raise PlanNotFoundError(plan.plan_id)
            self._plans[plan.plan_id] = plan
        return plan

    def compare_and_update(
        self,
        plan_id: str,
        predicate: Callable[[StoredPlan], bool],
        update_fn: Callable[[StoredPlan], StoredPlan],
    ) -> StoredPlan:
        """Atomically: read the plan, assert `predicate(plan)`, then
        replace it with `update_fn(plan)` - all under one lock acquisition.

        This is what makes execution's approved -> executing claim safe
        under concurrent requests: two calls racing for the same plan_id
        can't both observe `predicate` passing, because the whole
        check-then-write happens while holding the lock.
        """
        with self._lock:
            plan = self._plans.get(plan_id)
            if plan is None:
                raise PlanNotFoundError(plan_id)
            if not predicate(plan):
                raise PlanConflictError(plan_id, plan.status)
            updated = update_fn(plan)
            self._plans[plan_id] = updated
            return updated

    def clear(self) -> None:
        """Drop all stored plans. Mainly useful for test isolation."""
        with self._lock:
            self._plans.clear()


_repository = PlanRepository()


def get_plan_repository() -> PlanRepository:
    return _repository
