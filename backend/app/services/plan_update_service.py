"""Deterministic application logic for filling in a plan's missing fields.

Like approval_service.py, this never calls the LLM - it patches the
EXISTING StoredPlan's parameters with user-supplied values, then re-runs the
same deterministic enrichment/validation pipeline GENERATE_PLAN's output
already goes through (see app/agent/nodes/{enrich_datetime,
filter_optional_fields}.py and app/services/plan_validation.py), so a plan
that becomes fully specified lands back in "awaiting_approval" - it is never
auto-approved. The plan keeps its original plan_id throughout.
"""

from datetime import datetime, timezone
from typing import Any

from app.agent.nodes.enrich_datetime import resolve_calendar_datetime
from app.agent.nodes.filter_optional_fields import apply_filter_optional_fields
from app.core.config import get_settings
from app.models.stored_plan import ActionFieldValues, StoredPlan, StoredPlanStatus
from app.repositories.plan_repository import PlanRepository, get_plan_repository
from app.services.approval_service import InvalidPlanTransitionError
from app.services.plan_validation import validate_raw_plan

#: The only status a plan may have its missing fields filled in from.
UPDATABLE_STATUS = StoredPlanStatus.needs_clarification


class UnknownActionError(Exception):
    """Raised when an update references an action_id not in the plan."""

    def __init__(self, plan_id: str, action_id: str) -> None:
        self.plan_id = plan_id
        self.action_id = action_id
        super().__init__(f"Plan '{plan_id}' has no action with action_id '{action_id}'.")


class UnexpectedFieldError(Exception):
    """Raised when an update supplies a field that isn't currently missing.

    This endpoint only fills gaps reported by missing_information - it is
    deliberately not a general "edit any field" API.
    """

    def __init__(self, plan_id: str, action_id: str, field_names: list[str]) -> None:
        self.plan_id = plan_id
        self.action_id = action_id
        self.field_names = field_names
        fields = ", ".join(field_names)
        super().__init__(
            f"Action '{action_id}' in plan '{plan_id}' is not missing these fields, "
            f"so they cannot be set here: {fields}."
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PlanUpdateService:
    def __init__(self, repository: PlanRepository | None = None) -> None:
        self._repository = repository or get_plan_repository()

    def update_plan_fields(self, plan_id: str, updates: list[ActionFieldValues]) -> StoredPlan:
        plan = self._repository.get(plan_id)

        if plan.status != UPDATABLE_STATUS or plan.execution_plan is None:
            raise InvalidPlanTransitionError(
                plan_id,
                plan.status,
                f"Plan '{plan_id}' cannot have fields updated from status "
                f"'{plan.status.value}'. Only plans in '{UPDATABLE_STATUS.value}' "
                "may be updated.",
            )

        raw_plan = plan.execution_plan.model_dump(mode="json")
        actions_by_id: dict[str, dict[str, Any]] = {
            action["action_id"]: action for action in raw_plan["actions"]
        }

        for update in updates:
            action = actions_by_id.get(update.action_id)
            if action is None:
                raise UnknownActionError(plan_id, update.action_id)

            missing = action.get("missing_information") or []
            unexpected = [name for name in update.values if name not in missing]
            if unexpected:
                raise UnexpectedFieldError(plan_id, update.action_id, unexpected)

            parameters = action.setdefault("parameters", {})
            for field_name, value in update.values.items():
                parameters[field_name] = value
                missing.remove(field_name)
            action["missing_information"] = missing

            if action.get("tool") == "calendar":
                # A "date" and/or "time" value just supplied through the
                # missing-fields form is unambiguous (it came from a native
                # date/time picker, not free text) - no presence detection
                # needed here, only resolution of whatever is now present.
                resolve_calendar_datetime(parameters, get_settings().flowpilot_timezone)

        # Title inference is not re-run here - it depends on the original
        # free-text request, which this endpoint (structured field values,
        # not natural language) never receives.
        apply_filter_optional_fields(raw_plan)

        updated_execution_plan, errors = validate_raw_plan(raw_plan, plan_id=plan_id)
        if updated_execution_plan is None:
            # Structurally shouldn't happen - we started from an already-valid
            # ExecutionPlan and only ever merged known parameter values into
            # existing actions. Handled defensively rather than assumed away.
            raise InvalidPlanTransitionError(
                plan_id,
                plan.status,
                "Updating this plan's fields produced an invalid plan: "
                + "; ".join(f"{e.loc}: {e.message}" for e in errors),
            )

        new_status = (
            StoredPlanStatus.needs_clarification
            if updated_execution_plan.status.value == "needs_clarification"
            else StoredPlanStatus.awaiting_approval
        )

        updated = plan.model_copy(
            update={
                "execution_plan": updated_execution_plan,
                "status": new_status,
                "updated_at": _utcnow(),
            }
        )
        return self._repository.update(updated)


_service = PlanUpdateService()


def get_plan_update_service() -> PlanUpdateService:
    return _service
