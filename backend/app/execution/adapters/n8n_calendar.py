"""Executes calendar.create_event by calling the FlowPilot n8n workflow,
which is the only thing in this system that ever talks to Google
Calendar. Google credentials never enter this module, the LLM, or any
other part of the FastAPI backend - they live only in n8n's own
credential store.
"""

from datetime import timedelta

from app.core.config import get_settings
from app.core.logging import get_logger
from app.execution.adapters.base import ExecutionAdapter, ExecutionContext
from app.execution.n8n_client import N8nWebhookError, get_n8n_client
from app.execution.result import ActionExecutionResult, ActionExecutionStatus, ExecutionErrorDetail
from app.models.action import Action
from app.utils.datetime_parser import DatetimeNormalizationError, normalize_datetime

logger = get_logger(__name__)


def _failed(action: Action, code: str, message: str) -> ActionExecutionResult:
    return ActionExecutionResult(
        action_id=action.action_id,
        tool=action.tool,
        operation=action.operation,
        status=ActionExecutionStatus.failed,
        error=ExecutionErrorDetail(code=code, message=message),
    )


class N8nCalendarCreateEventAdapter(ExecutionAdapter):
    async def execute(self, action: Action, context: ExecutionContext) -> ActionExecutionResult:
        settings = get_settings()

        title = action.parameters.get("title")
        raw_datetime = action.parameters.get("datetime")
        if not title or not raw_datetime:
            return _failed(
                action,
                "MISSING_PARAMETERS",
                "Both 'title' and 'datetime' are required to create a calendar event.",
            )

        try:
            start = normalize_datetime(str(raw_datetime), settings.flowpilot_timezone)
        except DatetimeNormalizationError as exc:
            logger.warning(
                "datetime normalization failed for action %s: %s",
                action.action_id,
                exc.message,
                extra={"request_id": context.request_id},
            )
            return _failed(action, "DATETIME_NORMALIZATION_FAILED", exc.message)

        end = start + timedelta(minutes=settings.default_event_duration_minutes)

        webhook_url = settings.resolved_n8n_calendar_webhook_url
        if not webhook_url:
            return _failed(
                action,
                "N8N_NOT_CONFIGURED",
                "N8N_CALENDAR_WEBHOOK_URL (or N8N_BASE_URL) is not configured.",
            )

        # Payload contract shared with workflows/flowpilot_google_calendar.json's
        # "Validate Payload" node. n8n's Webhook node always nests this whole
        # object under its own `.body` wrapper (alongside headers/params/query)
        # before handing it to the next node - the workflow must read
        # `$input.item.json.body`, not `$input.item.json`.
        payload = {
            "request_id": context.request_id,
            "plan_id": context.plan_id,
            "action_id": action.action_id,
            "action": {
                "tool": action.tool.value,
                "operation": action.operation.value,
                "parameters": {
                    "title": title,
                    "start_datetime": start.isoformat(),
                    "end_datetime": end.isoformat(),
                    "timezone": settings.flowpilot_timezone,
                },
            },
        }

        try:
            body = await get_n8n_client().post(webhook_url, payload, settings.n8n_timeout_seconds)
        except N8nWebhookError as exc:
            logger.error(
                "n8n webhook call failed for action %s: [%s] %s",
                action.action_id,
                exc.code,
                exc.message,
                extra={"request_id": context.request_id},
            )
            return _failed(action, exc.code, exc.message)

        if body.get("success") is not True:
            code = str(body.get("error_code") or "N8N_EXECUTION_FAILED")
            message = str(body.get("message") or "n8n reported that the calendar event was not created.")
            logger.error(
                "n8n reported failure for action %s: [%s] %s",
                action.action_id,
                code,
                message,
                extra={"request_id": context.request_id},
            )
            return _failed(action, code, message)

        return ActionExecutionResult(
            action_id=action.action_id,
            tool=action.tool,
            operation=action.operation,
            status=ActionExecutionStatus.succeeded,
            result={
                "external_event_id": body.get("external_event_id"),
                "html_link": body.get("html_link"),
                "start_datetime": start.isoformat(),
                "end_datetime": end.isoformat(),
            },
        )
