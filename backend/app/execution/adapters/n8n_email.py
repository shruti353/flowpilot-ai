"""Executes email.send_email by calling the FlowPilot n8n email workflow,
which is the only thing in this system that ever talks to a real email
provider. Email credentials never enter this module, the LLM, or any
other part of the FastAPI backend - they live only in n8n's own
credential store (see workflows/flowpilot_email.json).

Only `email.send_email` is registered against this adapter (see
app/execution/dispatcher.py). `email.draft_email` and `email.search_email`
are deliberately left unregistered - the dispatcher's existing
"no adapter -> EXECUTION_NOT_SUPPORTED" behavior (app/execution/executor.py)
already reports them honestly instead of this adapter guessing that a
"draft" was meant to be "sent".
"""

from app.core.config import get_settings
from app.core.logging import get_logger
from app.execution.adapters.base import ExecutionAdapter, ExecutionContext
from app.execution.n8n_client import N8nWebhookError, get_n8n_client
from app.execution.result import ActionExecutionResult, ActionExecutionStatus, ExecutionErrorDetail
from app.models.action import Action

logger = get_logger(__name__)


def _failed(action: Action, code: str, message: str) -> ActionExecutionResult:
    return ActionExecutionResult(
        action_id=action.action_id,
        tool=action.tool,
        operation=action.operation,
        status=ActionExecutionStatus.failed,
        error=ExecutionErrorDetail(code=code, message=message),
    )


class N8nEmailSendAdapter(ExecutionAdapter):
    async def execute(self, action: Action, context: ExecutionContext) -> ActionExecutionResult:
        settings = get_settings()

        subject = action.parameters.get("subject")
        body = action.parameters.get("body")
        if not subject or not body:
            return _failed(
                action,
                "MISSING_PARAMETERS",
                "Both 'subject' and 'body' are required to send an email.",
            )

        # The only field this adapter ever reads to get an address: whatever
        # RESOLVE_RECIPIENTS (plan generation) or PlanUpdateService (missing-
        # fields flow) deterministically resolved. The raw "to" text the LLM
        # saw (a name, a team, free text) is never read or trusted here - if
        # resolution never ran or never succeeded, there is nothing to send
        # to, no matter what "to" says.
        resolved = action.parameters.get("resolved_recipients")
        recipient_emails = (
            [r["email"] for r in resolved if isinstance(r, dict) and r.get("email")]
            if isinstance(resolved, list)
            else []
        )
        if not recipient_emails:
            return _failed(
                action,
                "UNRESOLVED_RECIPIENTS",
                "No deterministically-resolved recipient addresses are available for this email.",
            )

        webhook_url = settings.resolved_n8n_email_webhook_url
        if not webhook_url:
            return _failed(
                action,
                "N8N_NOT_CONFIGURED",
                "N8N_EMAIL_WEBHOOK_URL (or N8N_BASE_URL) is not configured.",
            )

        # Payload contract shared with workflows/flowpilot_email.json's
        # "Validate Payload" node. Mirrors n8n_calendar.py's payload shape -
        # the Webhook node always nests the whole object under `.body`.
        payload = {
            "request_id": context.request_id,
            "plan_id": context.plan_id,
            "action_id": action.action_id,
            "action": {
                "tool": action.tool.value,
                "operation": action.operation.value,
                "parameters": {
                    "to": recipient_emails,
                    "subject": subject,
                    "body": body,
                },
            },
        }

        try:
            response_body = await get_n8n_client().post(webhook_url, payload, settings.n8n_timeout_seconds)
        except N8nWebhookError as exc:
            logger.error(
                "n8n webhook call failed for action %s: [%s] %s",
                action.action_id,
                exc.code,
                exc.message,
                extra={"request_id": context.request_id},
            )
            return _failed(action, exc.code, exc.message)

        if response_body.get("success") is not True:
            code = str(response_body.get("error_code") or "N8N_EXECUTION_FAILED")
            message = str(response_body.get("message") or "n8n reported that the email was not sent.")
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
                "recipients": recipient_emails,
                "subject": subject,
                "message_id": response_body.get("message_id"),
            },
        )
