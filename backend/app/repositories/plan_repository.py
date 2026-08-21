"""In-memory plan repository.

IMPORTANT: storage is entirely in-process memory (a plain dict behind a
lock). There is no database in Week 2 - every stored plan is lost the
moment the application process restarts. This is intentional for this
phase; a durable store is future work.
"""

import threading

from app.models.stored_plan import StoredPlan


class PlanNotFoundError(Exception):
    def __init__(self, plan_id: str) -> None:
        self.plan_id = plan_id
        super().__init__(f"No plan found with plan_id '{plan_id}'.")


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

    def clear(self) -> None:
        """Drop all stored plans. Mainly useful for test isolation."""
        with self._lock:
            self._plans.clear()


_repository = PlanRepository()


def get_plan_repository() -> PlanRepository:
    return _repository
