"""GET /api/v1/plans/{plan_id}, the approve/reject/cancel decision
endpoints (state changes only - no execution), and POST .../execute,
which is the only endpoint that ever performs a real external action
(via the execution service -> n8n -> Google Calendar)."""

from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException

from app.core.logging import get_logger
from app.models.stored_plan import (
    ApprovePlanResponse,
    CancelPlanResponse,
    ExecutePlanResponse,
    PlanErrorDetail,
    RejectPlanRequest,
    RejectPlanResponse,
    StoredPlan,
    StoredPlanStatus,
    UpdatePlanFieldsRequest,
    UpdatePlanFieldsResponse,
)
from app.repositories.plan_repository import PlanNotFoundError
from app.services.approval_service import InvalidPlanTransitionError, get_approval_service
from app.services.execution_service import get_execution_service
from app.services.plan_update_service import (
    UnexpectedFieldError,
    UnknownActionError,
    get_plan_update_service,
)

router = APIRouter(prefix="/plans", tags=["plans"])
logger = get_logger(__name__)

_EXECUTION_MESSAGES: dict[StoredPlanStatus, str] = {
    StoredPlanStatus.executed: "Plan executed successfully. All actions completed.",
    StoredPlanStatus.partially_executed: (
        "Plan partially executed - at least one action succeeded, but at "
        "least one failed or is not yet supported."
    ),
    StoredPlanStatus.execution_failed: "Plan execution failed. No action was completed.",
}


def _not_found(plan_id: str, exc: PlanNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=PlanErrorDetail(plan_id=plan_id, message=str(exc)).model_dump(mode="json"),
    )


def _conflict(exc: InvalidPlanTransitionError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=PlanErrorDetail(
            plan_id=exc.plan_id, message=exc.message, current_status=exc.current_status
        ).model_dump(mode="json"),
    )


@router.get("/{plan_id}", response_model=StoredPlan)
async def get_plan(plan_id: str) -> StoredPlan:
    try:
        return get_approval_service().get_plan(plan_id)
    except PlanNotFoundError as exc:
        raise _not_found(plan_id, exc) from exc


@router.post("/{plan_id}/approve", response_model=ApprovePlanResponse)
async def approve_plan(plan_id: str) -> ApprovePlanResponse:
    try:
        plan = get_approval_service().approve(plan_id)
    except PlanNotFoundError as exc:
        raise _not_found(plan_id, exc) from exc
    except InvalidPlanTransitionError as exc:
        raise _conflict(exc) from exc

    logger.info("plan approved", extra={"request_id": plan_id})
    return ApprovePlanResponse(
        plan_id=plan.plan_id,
        status=plan.status,
        message="Plan approved successfully. No actions have been executed.",
        plan=plan,
    )


@router.post("/{plan_id}/reject", response_model=RejectPlanResponse)
async def reject_plan(
    plan_id: str, payload: RejectPlanRequest | None = Body(default=None)
) -> RejectPlanResponse:
    reason = payload.reason if payload is not None else None
    try:
        plan = get_approval_service().reject(plan_id, reason)
    except PlanNotFoundError as exc:
        raise _not_found(plan_id, exc) from exc
    except InvalidPlanTransitionError as exc:
        raise _conflict(exc) from exc

    logger.info("plan rejected", extra={"request_id": plan_id})
    return RejectPlanResponse(
        plan_id=plan.plan_id,
        status=plan.status,
        message="Plan rejected.",
        rejection_reason=plan.rejection_reason,
        plan=plan,
    )


@router.post("/{plan_id}/cancel", response_model=CancelPlanResponse)
async def cancel_plan(plan_id: str) -> CancelPlanResponse:
    try:
        plan = get_approval_service().cancel(plan_id)
    except PlanNotFoundError as exc:
        raise _not_found(plan_id, exc) from exc
    except InvalidPlanTransitionError as exc:
        raise _conflict(exc) from exc

    logger.info("plan cancelled", extra={"request_id": plan_id})
    return CancelPlanResponse(
        plan_id=plan.plan_id,
        status=plan.status,
        message="Plan cancelled.",
        plan=plan,
    )


@router.post("/{plan_id}/fields", response_model=UpdatePlanFieldsResponse)
async def update_plan_fields(
    plan_id: str, payload: UpdatePlanFieldsRequest
) -> UpdatePlanFieldsResponse:
    try:
        plan = get_plan_update_service().update_plan_fields(plan_id, payload.actions)
    except PlanNotFoundError as exc:
        raise _not_found(plan_id, exc) from exc
    except InvalidPlanTransitionError as exc:
        raise _conflict(exc) from exc
    except UnknownActionError as exc:
        raise HTTPException(
            status_code=404,
            detail=PlanErrorDetail(plan_id=plan_id, message=str(exc)).model_dump(mode="json"),
        ) from exc
    except UnexpectedFieldError as exc:
        raise HTTPException(
            status_code=422,
            detail=PlanErrorDetail(plan_id=plan_id, message=str(exc)).model_dump(mode="json"),
        ) from exc

    logger.info("plan fields updated", extra={"request_id": plan_id})
    return UpdatePlanFieldsResponse(
        plan_id=plan.plan_id,
        status=plan.status,
        message=(
            "Plan updated and ready for approval."
            if plan.status == StoredPlanStatus.awaiting_approval
            else "Plan updated, but some required information is still missing."
        ),
        plan=plan,
    )


@router.post("/{plan_id}/execute", response_model=ExecutePlanResponse)
async def execute_plan(plan_id: str) -> ExecutePlanResponse:
    request_id = str(uuid4())
    logger.info("plan execution requested", extra={"request_id": request_id})

    try:
        plan = await get_execution_service().execute_plan(plan_id, request_id)
    except PlanNotFoundError as exc:
        raise _not_found(plan_id, exc) from exc
    except InvalidPlanTransitionError as exc:
        raise _conflict(exc) from exc

    logger.info(
        "plan execution finished with status '%s'",
        plan.status.value,
        extra={"request_id": request_id},
    )
    return ExecutePlanResponse(
        plan_id=plan.plan_id,
        status=plan.status,
        message=_EXECUTION_MESSAGES.get(plan.status, "Plan execution finished."),
        execution=plan.execution,
        plan=plan,
    )
