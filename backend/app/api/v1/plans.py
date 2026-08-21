"""GET /api/v1/plans/{plan_id} and the approve/reject/cancel decision
endpoints. These only ever change plan STATE - nothing here executes a
tool."""

from fastapi import APIRouter, Body, HTTPException

from app.core.logging import get_logger
from app.models.stored_plan import (
    ApprovePlanResponse,
    CancelPlanResponse,
    PlanErrorDetail,
    RejectPlanRequest,
    RejectPlanResponse,
    StoredPlan,
)
from app.repositories.plan_repository import PlanNotFoundError
from app.services.approval_service import InvalidPlanTransitionError, get_approval_service

router = APIRouter(prefix="/plans", tags=["plans"])
logger = get_logger(__name__)


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
