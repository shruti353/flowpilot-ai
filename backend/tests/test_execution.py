"""Tests for Week 3 approval-gated execution: dispatcher/adapter unit
tests plus the full approve -> execute API flow. All n8n calls are
mocked (FakeN8nClient) - nothing here needs a real n8n server, Google
Calendar credentials, or a real Ollama server.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app.execution.adapters.n8n_calendar as n8n_calendar_module
import app.execution.adapters.n8n_email as n8n_email_module
import app.execution.n8n_client as n8n_client
import app.services.ollama_service as ollama_service
from app.core.config import Settings
from app.execution.adapters.base import ExecutionContext
from app.execution.dispatcher import get_adapter
from app.execution.executor import execute_action
from app.execution.result import ActionExecutionStatus
from app.main import app
from app.models.action import Action
from app.models.execution_plan import ExecutionPlan
from app.models.stored_plan import NON_EXECUTABLE_STATUSES, StoredPlan, StoredPlanStatus
from app.repositories.plan_repository import get_plan_repository
from app.services.approval_service import InvalidPlanTransitionError, get_approval_service
from app.services.execution_service import get_execution_service
from tests.conftest import FakeN8nClient, FakeProvider

client = TestClient(app)

# Title is given directly; date+time are resolved deterministically from
# DEFAULT_TEXT below ("...tomorrow at 3 PM...") rather than from a "datetime"
# parameter, which is no longer trusted from the LLM for create_event.
VALID_RAW_PLAN = {
    "intent": "productivity_workflow",
    "summary": "Create a meeting and a preparation task.",
    "actions": [
        {
            "action_id": "action_1",
            "tool": "calendar",
            "operation": "create_event",
            "parameters": {"title": "AI Team Meeting"},
            "missing_information": [],
        },
        {
            "action_id": "action_2",
            "tool": "tasks",
            "operation": "create_task",
            "parameters": {"title": "Prepare the demo"},
            "missing_information": [],
        },
    ],
}

CALENDAR_ONLY_RAW_PLAN = {
    "intent": "productivity_workflow",
    "summary": "Create a meeting.",
    "actions": [
        {
            "action_id": "action_1",
            "tool": "calendar",
            "operation": "create_event",
            "parameters": {"title": "AI Team Meeting"},
            "missing_information": [],
        }
    ],
}

NEEDS_CLARIFICATION_RAW_PLAN = {
    "intent": "productivity_workflow",
    "summary": "Create a meeting; the title was not provided.",
    "actions": [
        {
            "action_id": "action_1",
            "tool": "calendar",
            "operation": "create_event",
            "parameters": {},
            "missing_information": ["title"],
        }
    ],
}

DEFAULT_TEXT = "Schedule a meeting with the AI team tomorrow at 3 PM and create a task to prepare the demo."


def _create_plan(raw_plan: dict, text: str = DEFAULT_TEXT) -> dict:
    ollama_service.set_llm_provider(FakeProvider(result=raw_plan))
    response = client.post("/api/v1/agent/plan", json={"text": text})
    assert response.status_code == 200
    return response.json()


def _create_and_approve_plan(raw_plan: dict = CALENDAR_ONLY_RAW_PLAN, text: str = DEFAULT_TEXT) -> str:
    plan_id = _create_plan(raw_plan, text=text)["plan_id"]
    approve_response = client.post(f"/api/v1/plans/{plan_id}/approve")
    assert approve_response.status_code == 200
    return plan_id


CALENDAR_WEBHOOK_URL = "http://n8n.test/webhook/flowpilot-calendar"
EMAIL_WEBHOOK_URL = "http://n8n.test/webhook/flowpilot-email"


@pytest.fixture
def configured_settings(monkeypatch):
    settings = Settings(
        n8n_calendar_webhook_url=CALENDAR_WEBHOOK_URL,
        n8n_email_webhook_url=EMAIL_WEBHOOK_URL,
        flowpilot_timezone="Asia/Kolkata",
        default_event_duration_minutes=60,
        n8n_timeout_seconds=5,
    )
    monkeypatch.setattr(n8n_calendar_module, "get_settings", lambda: settings)
    monkeypatch.setattr(n8n_email_module, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def unconfigured_settings(monkeypatch):
    settings = Settings(
        n8n_calendar_webhook_url=None,
        n8n_email_webhook_url=None,
        n8n_base_url=None,
        flowpilot_timezone="Asia/Kolkata",
        default_event_duration_minutes=60,
        n8n_timeout_seconds=5,
    )
    monkeypatch.setattr(n8n_calendar_module, "get_settings", lambda: settings)
    monkeypatch.setattr(n8n_email_module, "get_settings", lambda: settings)
    return settings


class PerUrlFakeN8nClient:
    """Test double for N8nClient that returns a different canned response per
    webhook URL - needed to simulate "calendar succeeds, email fails" (or
    vice versa) within a single multi-action execution, which the shared
    FakeN8nClient (one canned response for every call) can't express."""

    def __init__(self, responses: dict[str, dict] | None = None, errors: dict[str, Exception] | None = None):
        self.responses = responses or {}
        self.errors = errors or {}
        self.calls: list[dict] = []

    async def post(self, url: str, payload: dict, timeout_seconds: float):
        self.calls.append({"url": url, "payload": payload, "timeout_seconds": timeout_seconds})
        if url in self.errors:
            raise self.errors[url]
        return self.responses.get(url, {"success": True})

    def calls_to(self, url: str) -> list[dict]:
        return [call for call in self.calls if call["url"] == url]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def test_dispatcher_finds_adapter_for_calendar_create_event():
    from app.models.action import OperationName, ToolName

    adapter = get_adapter(ToolName.calendar, OperationName.create_event)
    assert adapter is not None


def test_dispatcher_finds_adapter_for_email_send_email():
    from app.models.action import OperationName, ToolName

    adapter = get_adapter(ToolName.email, OperationName.send_email)
    assert adapter is not None


@pytest.mark.parametrize(
    "tool,operation",
    [
        ("calendar", "get_event"),
        ("tasks", "create_task"),
        ("tasks", "get_task"),
        ("email", "draft_email"),
        ("email", "search_email"),
    ],
)
def test_dispatcher_has_no_adapter_for_unsupported_operations(tool, operation):
    from app.models.action import OperationName, ToolName

    adapter = get_adapter(ToolName(tool), OperationName(operation))
    assert adapter is None


# ---------------------------------------------------------------------------
# Executor / adapter (direct unit tests, no HTTP, no repository)
# ---------------------------------------------------------------------------


def _action(**overrides) -> Action:
    defaults = dict(
        action_id="action_1",
        tool="calendar",
        operation="create_event",
        parameters={"title": "AI Team Meeting", "datetime": "tomorrow at 3 PM"},
    )
    defaults.update(overrides)
    return Action(**defaults)


@pytest.mark.asyncio
async def test_unsupported_action_never_reaches_the_calendar_adapter(configured_settings):
    fake_client = FakeN8nClient()
    n8n_client.set_n8n_client(fake_client)

    action = Action(
        action_id="action_2",
        tool="tasks",
        operation="create_task",
        parameters={"title": "Prepare the demo"},
    )
    result = await execute_action(action, ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.status == ActionExecutionStatus.unsupported
    assert result.error.code == "EXECUTION_NOT_SUPPORTED"
    assert fake_client.calls == []


@pytest.mark.asyncio
async def test_calendar_adapter_succeeds_and_calls_n8n_with_normalized_datetime(configured_settings):
    fake_client = FakeN8nClient(
        result={"success": True, "external_event_id": "evt_123", "html_link": "https://calendar.example/evt_123"}
    )
    n8n_client.set_n8n_client(fake_client)

    result = await execute_action(_action(), ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.status == ActionExecutionStatus.succeeded
    assert result.result["external_event_id"] == "evt_123"
    assert result.result["html_link"] == "https://calendar.example/evt_123"
    assert len(fake_client.calls) == 1
    sent_action = fake_client.calls[0]["payload"]["action"]
    assert sent_action["tool"] == "calendar"
    assert sent_action["operation"] == "create_event"
    # A concrete, timezone-aware ISO datetime - not the raw "tomorrow at 3 PM".
    assert "tomorrow" not in sent_action["parameters"]["start_datetime"]
    assert "+05:30" in sent_action["parameters"]["start_datetime"]


@pytest.mark.asyncio
async def test_calendar_adapter_sends_the_documented_payload_contract(configured_settings):
    # Pins the exact payload shape workflows/flowpilot_google_calendar.json's
    # "Validate Payload" node expects: { request_id, plan_id, action_id,
    # action: { tool, operation, parameters: { title, start_datetime,
    # end_datetime, timezone } } }. A silent shape drift here is exactly
    # what broke the live integration before (see test_n8n_workflow_contract.py
    # for the matching workflow-side assertions).
    fake_client = FakeN8nClient(
        result={"success": True, "external_event_id": "evt_123", "html_link": "https://calendar.example/evt_123"}
    )
    n8n_client.set_n8n_client(fake_client)

    await execute_action(_action(), ExecutionContext(request_id="req-1", plan_id="plan-1"))

    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]
    payload = call["payload"]

    assert set(payload.keys()) == {"request_id", "plan_id", "action_id", "action"}
    assert payload["request_id"] == "req-1"
    assert payload["plan_id"] == "plan-1"
    assert payload["action_id"] == "action_1"

    action_payload = payload["action"]
    assert action_payload["tool"] == "calendar"
    assert action_payload["operation"] == "create_event"

    parameters = action_payload["parameters"]
    assert set(parameters.keys()) == {"title", "start_datetime", "end_datetime", "timezone"}
    assert parameters["title"] == "AI Team Meeting"
    assert parameters["timezone"] == "Asia/Kolkata"
    # Concrete ISO 8601 datetimes with the Asia/Kolkata offset, never the
    # raw relative expression.
    assert parameters["start_datetime"].endswith("+05:30")
    assert parameters["end_datetime"].endswith("+05:30")
    assert "T" in parameters["start_datetime"]


def test_title_inference_and_datetime_enrichment_reach_the_n8n_payload(configured_settings):
    # End-to-end regression for the exact reported request: the LLM leaves
    # the title out and only gives a relative datetime; INFER_TITLES and
    # ENRICH_DATETIME run at plan-generation time, but the adapter
    # independently re-normalizes the raw "datetime" text at execution
    # time - both paths must agree on "AI Team Meeting" and a concrete
    # +05:30 datetime by the time n8n is called.
    fake_client = FakeN8nClient(
        result={"success": True, "external_event_id": "evt_1", "html_link": "https://cal/evt_1"}
    )
    n8n_client.set_n8n_client(fake_client)

    raw_plan = {
        "intent": "productivity_workflow",
        "summary": "Create a meeting; the title was not provided.",
        "actions": [
            {
                "action_id": "action_1",
                "tool": "calendar",
                "operation": "create_event",
                "parameters": {"datetime": "tomorrow at 3 PM"},
                "missing_information": ["title"],
            }
        ],
    }
    plan_response = _create_plan(raw_plan, text="Schedule a meeting with the AI team for tomorrow at 3 PM")
    assert plan_response["execution_plan"]["status"] == "ready"
    inferred_action = plan_response["execution_plan"]["actions"][0]
    assert inferred_action["parameters"]["title"] == "AI Team Meeting"
    assert inferred_action["parameters"]["resolved_datetime"].endswith("+05:30")

    plan_id = plan_response["plan_id"]
    assert client.post(f"/api/v1/plans/{plan_id}/approve").status_code == 200

    response = client.post(f"/api/v1/plans/{plan_id}/execute")
    assert response.status_code == 200
    assert response.json()["status"] == "executed"

    sent_parameters = fake_client.calls[0]["payload"]["action"]["parameters"]
    assert sent_parameters["title"] == "AI Team Meeting"
    assert sent_parameters["start_datetime"].endswith("+05:30")
    assert "tomorrow" not in sent_parameters["start_datetime"]


@pytest.mark.asyncio
async def test_invalid_datetime_does_not_call_n8n(configured_settings):
    fake_client = FakeN8nClient()
    n8n_client.set_n8n_client(fake_client)

    action = _action(parameters={"title": "AI Team Meeting", "datetime": "gibberish nonsense"})
    result = await execute_action(action, ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.status == ActionExecutionStatus.failed
    assert result.error.code == "DATETIME_NORMALIZATION_FAILED"
    assert fake_client.calls == []


@pytest.mark.asyncio
async def test_n8n_failure_response_marks_action_failed(configured_settings):
    n8n_client.set_n8n_client(
        FakeN8nClient(result={"success": False, "error_code": "CALENDAR_API_ERROR", "message": "quota exceeded"})
    )

    result = await execute_action(_action(), ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.status == ActionExecutionStatus.failed
    assert result.error.code == "CALENDAR_API_ERROR"
    assert result.error.message == "quota exceeded"


@pytest.mark.asyncio
async def test_n8n_unreachable_marks_action_failed(configured_settings):
    n8n_client.set_n8n_client(
        FakeN8nClient(error=n8n_client.N8nWebhookError("N8N_UNREACHABLE", "connection refused"))
    )

    result = await execute_action(_action(), ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.status == ActionExecutionStatus.failed
    assert result.error.code == "N8N_UNREACHABLE"


@pytest.mark.asyncio
async def test_n8n_not_configured_marks_action_failed_without_a_client_call(unconfigured_settings):
    fake_client = FakeN8nClient()
    n8n_client.set_n8n_client(fake_client)

    result = await execute_action(_action(), ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.status == ActionExecutionStatus.failed
    assert result.error.code == "N8N_NOT_CONFIGURED"
    assert fake_client.calls == []


# ---------------------------------------------------------------------------
# Week 5 Day 5: email.send_email adapter (direct unit tests)
# ---------------------------------------------------------------------------


def _email_action(**overrides) -> Action:
    defaults = dict(
        action_id="action_2",
        tool="email",
        operation="send_email",
        parameters={
            "to": "AI Team",
            "subject": "Project Update",
            "body": "Here is the update.",
            # Only ever set by deterministic resolution (RESOLVE_RECIPIENTS /
            # PlanUpdateService) - never by the LLM. See
            # app/services/contact_resolution_service.py.
            "resolved_recipients": [
                {"name": "Alice", "email": "alice@example.com"},
                {"name": "Bob", "email": "bob@example.com"},
            ],
        },
    )
    defaults.update(overrides)
    return Action(**defaults)


@pytest.mark.asyncio
async def test_email_adapter_succeeds_with_multiple_resolved_recipients(configured_settings):
    fake_client = FakeN8nClient(result={"success": True, "message_id": "msg_123"})
    n8n_client.set_n8n_client(fake_client)

    result = await execute_action(_email_action(), ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.status == ActionExecutionStatus.succeeded
    assert result.result["recipients"] == ["alice@example.com", "bob@example.com"]
    assert result.result["message_id"] == "msg_123"
    assert len(fake_client.calls) == 1


@pytest.mark.asyncio
async def test_email_adapter_sends_the_documented_payload_contract(configured_settings):
    # Pins the exact payload shape workflows/flowpilot_email.json's
    # "Validate Payload" node expects - mirrors the calendar adapter's
    # equivalent pinning test above.
    fake_client = FakeN8nClient(result={"success": True, "message_id": "msg_123"})
    n8n_client.set_n8n_client(fake_client)

    await execute_action(_email_action(), ExecutionContext(request_id="req-1", plan_id="plan-1"))

    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]
    payload = call["payload"]

    assert set(payload.keys()) == {"request_id", "plan_id", "action_id", "action"}
    assert payload["request_id"] == "req-1"
    assert payload["plan_id"] == "plan-1"
    assert payload["action_id"] == "action_2"

    action_payload = payload["action"]
    assert action_payload["tool"] == "email"
    assert action_payload["operation"] == "send_email"

    parameters = action_payload["parameters"]
    assert set(parameters.keys()) == {"to", "subject", "body"}
    # Only the deterministically-resolved addresses ever reach the payload -
    # never the raw "to" reference ("AI Team") the LLM saw.
    assert parameters["to"] == ["alice@example.com", "bob@example.com"]
    assert parameters["subject"] == "Project Update"
    assert parameters["body"] == "Here is the update."


@pytest.mark.asyncio
async def test_email_adapter_fails_without_resolved_recipients(configured_settings):
    # No deterministic resolution ever ran (or it failed) - "to" being
    # present as free text is never trusted as an address.
    fake_client = FakeN8nClient()
    n8n_client.set_n8n_client(fake_client)

    action = _email_action(parameters={"to": "Unknown Team", "subject": "Update", "body": "Hi"})
    result = await execute_action(action, ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.status == ActionExecutionStatus.failed
    assert result.error.code == "UNRESOLVED_RECIPIENTS"
    # Week 5 Day 6: a pre-flight check that never reached n8n is a
    # validation-stage failure, not a "workflow" one.
    assert result.error.stage == "validation"
    assert fake_client.calls == []


@pytest.mark.asyncio
async def test_email_adapter_fails_without_subject(configured_settings):
    fake_client = FakeN8nClient()
    n8n_client.set_n8n_client(fake_client)

    action = _email_action(
        parameters={
            "to": "AI Team",
            "body": "Hi",
            "resolved_recipients": [{"name": "Alice", "email": "alice@example.com"}],
        }
    )
    result = await execute_action(action, ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.status == ActionExecutionStatus.failed
    assert result.error.code == "MISSING_PARAMETERS"
    assert fake_client.calls == []


@pytest.mark.asyncio
async def test_email_adapter_fails_without_body(configured_settings):
    fake_client = FakeN8nClient()
    n8n_client.set_n8n_client(fake_client)

    action = _email_action(
        parameters={
            "to": "AI Team",
            "subject": "Update",
            "resolved_recipients": [{"name": "Alice", "email": "alice@example.com"}],
        }
    )
    result = await execute_action(action, ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.status == ActionExecutionStatus.failed
    assert result.error.code == "MISSING_PARAMETERS"
    assert fake_client.calls == []


@pytest.mark.asyncio
async def test_draft_email_action_never_reaches_the_email_adapter(configured_settings):
    # email.draft_email has no registered adapter (see dispatcher.py) - a
    # "draft" request is never silently promoted to a real send.
    fake_client = FakeN8nClient()
    n8n_client.set_n8n_client(fake_client)

    action = Action(
        action_id="action_2",
        tool="email",
        operation="draft_email",
        parameters={
            "to": "AI Team",
            "subject": "Update",
            "body": "Hi",
            "resolved_recipients": [{"name": "Alice", "email": "alice@example.com"}],
        },
    )
    result = await execute_action(action, ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.status == ActionExecutionStatus.unsupported
    assert result.error.code == "EXECUTION_NOT_SUPPORTED"
    assert fake_client.calls == []


@pytest.mark.asyncio
async def test_email_n8n_failure_response_marks_action_failed(configured_settings):
    n8n_client.set_n8n_client(
        FakeN8nClient(result={"success": False, "error_code": "SMTP_AUTH_FAILED", "message": "bad credentials"})
    )

    result = await execute_action(_email_action(), ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.status == ActionExecutionStatus.failed
    assert result.error.code == "SMTP_AUTH_FAILED"
    assert result.error.message == "bad credentials"
    # Week 5 Day 6: n8n ran and told us it failed - a workflow-stage failure.
    assert result.error.stage == "workflow"


@pytest.mark.asyncio
async def test_email_n8n_unreachable_marks_action_failed(configured_settings):
    n8n_client.set_n8n_client(
        FakeN8nClient(error=n8n_client.N8nWebhookError("N8N_UNREACHABLE", "connection refused"))
    )

    result = await execute_action(_email_action(), ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.status == ActionExecutionStatus.failed
    assert result.error.code == "N8N_UNREACHABLE"
    assert result.error.stage == "transport"


@pytest.mark.asyncio
async def test_email_n8n_not_configured_marks_action_failed_without_a_client_call(unconfigured_settings):
    fake_client = FakeN8nClient()
    n8n_client.set_n8n_client(fake_client)

    result = await execute_action(_email_action(), ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.status == ActionExecutionStatus.failed
    assert result.error.code == "N8N_NOT_CONFIGURED"
    assert result.error.stage == "configuration"
    assert fake_client.calls == []


# ---------------------------------------------------------------------------
# Execution service: state-machine gating (direct, synthetic statuses)
# ---------------------------------------------------------------------------


def _synthetic_plan(status: StoredPlanStatus) -> StoredPlan:
    now = datetime.now(timezone.utc)
    execution_plan = ExecutionPlan(
        plan_id="synthetic-plan",
        intent="productivity_workflow",
        summary="Create a meeting.",
        actions=[_action()],
    )
    return StoredPlan(
        plan_id="synthetic-plan",
        status=status,
        execution_plan=execution_plan,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", sorted(NON_EXECUTABLE_STATUSES, key=lambda s: s.value))
async def test_plan_cannot_execute_from_any_non_approved_status(status):
    get_plan_repository().add(_synthetic_plan(status))

    with pytest.raises(InvalidPlanTransitionError) as exc_info:
        await get_execution_service().execute_plan("synthetic-plan", request_id="r1")

    assert exc_info.value.current_status == status


# ---------------------------------------------------------------------------
# Full API flow: agent/plan -> approve -> execute
# ---------------------------------------------------------------------------


def test_approved_plan_can_execute_successfully(configured_settings):
    n8n_client.set_n8n_client(
        FakeN8nClient(result={"success": True, "external_event_id": "evt_1", "html_link": "https://cal/evt_1"})
    )
    plan_id = _create_and_approve_plan()

    response = client.post(f"/api/v1/plans/{plan_id}/execute")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "executed"
    assert body["execution"]["status"] == "success"
    assert body["execution"]["actions"][0]["status"] == "succeeded"
    assert body["execution"]["actions"][0]["result"]["external_event_id"] == "evt_1"


def test_awaiting_approval_plan_cannot_execute(configured_settings):
    plan_id = _create_plan(CALENDAR_ONLY_RAW_PLAN)["plan_id"]

    response = client.post(f"/api/v1/plans/{plan_id}/execute")

    assert response.status_code == 409
    assert response.json()["detail"]["current_status"] == "awaiting_approval"


def test_rejected_plan_cannot_execute(configured_settings):
    plan_id = _create_plan(CALENDAR_ONLY_RAW_PLAN)["plan_id"]
    assert client.post(f"/api/v1/plans/{plan_id}/reject").status_code == 200

    response = client.post(f"/api/v1/plans/{plan_id}/execute")

    assert response.status_code == 409
    assert response.json()["detail"]["current_status"] == "rejected"


def test_cancelled_plan_cannot_execute(configured_settings):
    plan_id = _create_plan(CALENDAR_ONLY_RAW_PLAN)["plan_id"]
    assert client.post(f"/api/v1/plans/{plan_id}/cancel").status_code == 200

    response = client.post(f"/api/v1/plans/{plan_id}/execute")

    assert response.status_code == 409
    assert response.json()["detail"]["current_status"] == "cancelled"


def test_needs_clarification_plan_cannot_execute(configured_settings):
    plan_id = _create_plan(NEEDS_CLARIFICATION_RAW_PLAN, text="Schedule a meeting.")["plan_id"]

    response = client.post(f"/api/v1/plans/{plan_id}/execute")

    assert response.status_code == 409
    assert response.json()["detail"]["current_status"] == "needs_clarification"


def test_multi_action_plan_with_one_incomplete_action_cannot_execute(configured_settings):
    # Week 5 Day 3: even when one action in a multi-action plan (here, the
    # calendar action) is fully specified and would execute fine on its
    # own, the plan as a whole stays "needs_clarification" - and therefore
    # blocked from /execute entirely - as long as ANY action (here, the
    # email action) is still missing required information. Partial
    # execution is never triggered by field-completeness; only an explicit
    # approve on a fully-specified plan can lead to execution.
    raw_plan = {
        "intent": "productivity_workflow",
        "summary": "Schedule a meeting and email the AI team.",
        "actions": [
            {
                "action_id": "action_1",
                "tool": "calendar",
                "operation": "create_event",
                "parameters": {"title": "AI Team Meeting"},
                "missing_information": [],
            },
            {
                "action_id": "action_2",
                "tool": "email",
                "operation": "send_email",
                "parameters": {"to": "AI Team"},
                "missing_information": ["subject", "body"],
            },
        ],
    }
    created = _create_plan(raw_plan, text=DEFAULT_TEXT)
    assert created["status"] == "needs_clarification"

    response = client.post(f"/api/v1/plans/{created['plan_id']}/execute")

    assert response.status_code == 409
    assert response.json()["detail"]["current_status"] == "needs_clarification"


def test_duplicate_execute_request_does_not_call_n8n_twice(configured_settings):
    fake_client = FakeN8nClient(result={"success": True, "external_event_id": "evt_1", "html_link": "https://cal/evt_1"})
    n8n_client.set_n8n_client(fake_client)
    plan_id = _create_and_approve_plan()

    first = client.post(f"/api/v1/plans/{plan_id}/execute")
    assert first.status_code == 200
    assert first.json()["status"] == "executed"

    second = client.post(f"/api/v1/plans/{plan_id}/execute")
    assert second.status_code == 409
    assert second.json()["detail"]["current_status"] == "executed"

    assert len(fake_client.calls) == 1


def test_mixed_plan_reports_partial_execution_accurately(configured_settings):
    n8n_client.set_n8n_client(
        FakeN8nClient(result={"success": True, "external_event_id": "evt_1", "html_link": "https://cal/evt_1"})
    )
    plan_id = _create_and_approve_plan(VALID_RAW_PLAN)

    response = client.post(f"/api/v1/plans/{plan_id}/execute")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partially_executed"
    assert body["execution"]["status"] == "partial"

    by_action_id = {a["action_id"]: a for a in body["execution"]["actions"]}
    assert by_action_id["action_1"]["status"] == "succeeded"
    assert by_action_id["action_2"]["status"] == "unsupported"
    assert by_action_id["action_2"]["error"]["code"] == "EXECUTION_NOT_SUPPORTED"


def test_all_actions_failing_reports_execution_failed(configured_settings):
    n8n_client.set_n8n_client(
        FakeN8nClient(result={"success": False, "error_code": "CALENDAR_API_ERROR", "message": "boom"})
    )
    plan_id = _create_and_approve_plan()

    response = client.post(f"/api/v1/plans/{plan_id}/execute")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "execution_failed"
    assert body["execution"]["status"] == "failed"


def test_execute_unknown_plan_id_returns_404(configured_settings):
    response = client.post("/api/v1/plans/does-not-exist/execute")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Week 4: idempotent retries - a succeeded action must never be re-sent to
# n8n, but a failed/unsupported action may be retried.
# ---------------------------------------------------------------------------


def test_retry_of_partially_executed_plan_does_not_recall_n8n_for_the_succeeded_action(
    configured_settings,
):
    fake_client = FakeN8nClient(
        result={"success": True, "external_event_id": "evt_1", "html_link": "https://cal/evt_1"}
    )
    n8n_client.set_n8n_client(fake_client)
    plan_id = _create_and_approve_plan(VALID_RAW_PLAN)  # action_1 calendar, action_2 tasks (unsupported)

    first = client.post(f"/api/v1/plans/{plan_id}/execute")
    assert first.status_code == 200
    assert first.json()["status"] == "partially_executed"
    assert len(fake_client.calls) == 1

    second = client.post(f"/api/v1/plans/{plan_id}/execute")
    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "partially_executed"

    # The already-succeeded calendar action was never re-dispatched.
    assert len(fake_client.calls) == 1

    by_action_id = {a["action_id"]: a for a in body["execution"]["actions"]}
    assert by_action_id["action_1"]["status"] == "succeeded"
    assert by_action_id["action_1"]["attempt_count"] == 1
    # The unsupported action has no adapter to retry against, but it IS
    # re-attempted (attempt_count increments) rather than silently skipped.
    assert by_action_id["action_2"]["status"] == "unsupported"
    assert by_action_id["action_2"]["attempt_count"] == 2


def test_retry_after_transient_n8n_failure_succeeds_and_increments_attempt_count(
    configured_settings,
):
    failing_client = FakeN8nClient(
        error=n8n_client.N8nWebhookError("N8N_UNREACHABLE", "connection refused")
    )
    n8n_client.set_n8n_client(failing_client)
    plan_id = _create_and_approve_plan()  # CALENDAR_ONLY_RAW_PLAN

    first = client.post(f"/api/v1/plans/{plan_id}/execute")
    assert first.status_code == 200
    assert first.json()["status"] == "execution_failed"
    assert len(failing_client.calls) == 1

    # Fix the outage, then retry the SAME plan.
    succeeding_client = FakeN8nClient(
        result={"success": True, "external_event_id": "evt_1", "html_link": "https://cal/evt_1"}
    )
    n8n_client.set_n8n_client(succeeding_client)

    second = client.post(f"/api/v1/plans/{plan_id}/execute")
    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "executed"
    assert len(succeeding_client.calls) == 1  # exactly one retry call, not zero, not two

    action = body["execution"]["actions"][0]
    assert action["status"] == "succeeded"
    assert action["attempt_count"] == 2  # one failed attempt + one successful retry


def test_fully_executed_plan_cannot_be_retried(configured_settings):
    n8n_client.set_n8n_client(
        FakeN8nClient(result={"success": True, "external_event_id": "evt_1", "html_link": "https://cal/evt_1"})
    )
    plan_id = _create_and_approve_plan()

    assert client.post(f"/api/v1/plans/{plan_id}/execute").json()["status"] == "executed"

    response = client.post(f"/api/v1/plans/{plan_id}/execute")
    assert response.status_code == 409
    assert response.json()["detail"]["current_status"] == "executed"


# ---------------------------------------------------------------------------
# Week 4: downstream error transparency (error.stage classification)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_parameters_error_is_classified_as_validation_stage(configured_settings):
    action = Action(action_id="action_1", tool="calendar", operation="create_event", parameters={})
    result = await execute_action(action, ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.error.code == "MISSING_PARAMETERS"
    assert result.error.stage == "validation"


@pytest.mark.asyncio
async def test_not_configured_error_is_classified_as_configuration_stage(unconfigured_settings):
    result = await execute_action(_action(), ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.error.code == "N8N_NOT_CONFIGURED"
    assert result.error.stage == "configuration"


@pytest.mark.asyncio
async def test_unreachable_error_is_classified_as_transport_stage(configured_settings):
    n8n_client.set_n8n_client(
        FakeN8nClient(error=n8n_client.N8nWebhookError("N8N_UNREACHABLE", "connection refused"))
    )
    result = await execute_action(_action(), ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.error.stage == "transport"


@pytest.mark.asyncio
async def test_n8n_reported_failure_is_classified_as_workflow_stage(configured_settings):
    n8n_client.set_n8n_client(
        FakeN8nClient(result={"success": False, "error_code": "CALENDAR_API_ERROR", "message": "quota exceeded"})
    )
    result = await execute_action(_action(), ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.error.stage == "workflow"


@pytest.mark.asyncio
async def test_unsupported_action_error_is_classified_as_unsupported_stage(configured_settings):
    action = Action(action_id="action_2", tool="tasks", operation="create_task", parameters={"title": "x"})
    result = await execute_action(action, ExecutionContext(request_id="r1", plan_id="p1"))

    assert result.error.stage == "unsupported"


# ---------------------------------------------------------------------------
# Week 5 Day 3/4: multi-action plans - email.draft_email genuinely has no
# execution adapter (by design - a "draft" is never silently promoted to a
# real send), calendar still executes and retries independently.
# ---------------------------------------------------------------------------


CALENDAR_AND_DRAFT_EMAIL_RAW_PLAN = {
    "intent": "productivity_workflow",
    "summary": "Schedule a meeting and draft an email about it.",
    "actions": [
        {
            "action_id": "action_1",
            "tool": "calendar",
            "operation": "create_event",
            "parameters": {"title": "AI Team Meeting"},
            "missing_information": [],
        },
        {
            "action_id": "action_2",
            "tool": "email",
            "operation": "draft_email",
            "parameters": {"to": "adarsh@example.com", "subject": "Update", "body": "Hi"},
            "missing_information": [],
        },
    ],
}
CALENDAR_AND_DRAFT_EMAIL_TEXT = (
    "Schedule a meeting with the AI team tomorrow at 3 PM and draft an email to adarsh@example.com about it."
)


def test_draft_email_action_is_unsupported_and_does_not_block_calendar_execution(configured_settings):
    n8n_client.set_n8n_client(
        FakeN8nClient(result={"success": True, "external_event_id": "evt_1", "html_link": "https://cal/evt_1"})
    )
    plan_id = _create_and_approve_plan(CALENDAR_AND_DRAFT_EMAIL_RAW_PLAN, text=CALENDAR_AND_DRAFT_EMAIL_TEXT)

    response = client.post(f"/api/v1/plans/{plan_id}/execute")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partially_executed"

    by_action_id = {a["action_id"]: a for a in body["execution"]["actions"]}
    assert by_action_id["action_1"]["status"] == "succeeded"
    assert by_action_id["action_2"]["status"] == "unsupported"
    assert by_action_id["action_2"]["error"]["code"] == "EXECUTION_NOT_SUPPORTED"


def test_retrying_calendar_and_draft_email_plan_never_recalls_n8n_for_the_succeeded_calendar_action(
    configured_settings,
):
    fake_client = FakeN8nClient(
        result={"success": True, "external_event_id": "evt_1", "html_link": "https://cal/evt_1"}
    )
    n8n_client.set_n8n_client(fake_client)
    plan_id = _create_and_approve_plan(CALENDAR_AND_DRAFT_EMAIL_RAW_PLAN, text=CALENDAR_AND_DRAFT_EMAIL_TEXT)

    first = client.post(f"/api/v1/plans/{plan_id}/execute")
    assert first.status_code == 200
    assert first.json()["status"] == "partially_executed"
    assert len(fake_client.calls) == 1

    second = client.post(f"/api/v1/plans/{plan_id}/execute")
    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "partially_executed"

    # The already-succeeded calendar action was never re-dispatched to n8n.
    assert len(fake_client.calls) == 1
    by_action_id = {a["action_id"]: a for a in body["execution"]["actions"]}
    assert by_action_id["action_1"]["attempt_count"] == 1
    assert by_action_id["action_2"]["attempt_count"] == 2


# ---------------------------------------------------------------------------
# Week 5 Day 5: real multi-action execution with a SUPPORTED email.send_email
# action - calendar and email coexist in the same plan, execute
# independently, and a retry never re-sends whichever one already succeeded.
# ---------------------------------------------------------------------------


CALENDAR_AND_SEND_EMAIL_RAW_PLAN = {
    "intent": "productivity_workflow",
    "summary": "Schedule a meeting and send an email about it.",
    "actions": [
        {
            "action_id": "action_1",
            "tool": "calendar",
            "operation": "create_event",
            "parameters": {"title": "AI Team Meeting"},
            "missing_information": [],
        },
        {
            "action_id": "action_2",
            "tool": "email",
            "operation": "send_email",
            "parameters": {"to": "adarsh@example.com", "subject": "Project Update", "body": "Here is the update."},
            "missing_information": [],
        },
    ],
}
CALENDAR_AND_SEND_EMAIL_TEXT = (
    "Schedule a meeting with the AI team tomorrow at 3 PM and send adarsh@example.com "
    "an email about the project update."
)


def test_calendar_and_email_plan_cannot_execute_before_approval(configured_settings):
    plan_id = _create_plan(CALENDAR_AND_SEND_EMAIL_RAW_PLAN, text=CALENDAR_AND_SEND_EMAIL_TEXT)["plan_id"]

    response = client.post(f"/api/v1/plans/{plan_id}/execute")

    assert response.status_code == 409
    assert response.json()["detail"]["current_status"] == "awaiting_approval"


def test_calendar_and_email_both_succeed_reports_executed(configured_settings):
    fake_client = PerUrlFakeN8nClient(
        responses={
            CALENDAR_WEBHOOK_URL: {"success": True, "external_event_id": "evt_1", "html_link": "https://cal/evt_1"},
            EMAIL_WEBHOOK_URL: {"success": True, "message_id": "msg_1"},
        }
    )
    n8n_client.set_n8n_client(fake_client)
    plan_id = _create_and_approve_plan(CALENDAR_AND_SEND_EMAIL_RAW_PLAN, text=CALENDAR_AND_SEND_EMAIL_TEXT)

    response = client.post(f"/api/v1/plans/{plan_id}/execute")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "executed"
    assert body["execution"]["status"] == "success"

    by_action_id = {a["action_id"]: a for a in body["execution"]["actions"]}
    assert by_action_id["action_1"]["status"] == "succeeded"
    assert by_action_id["action_2"]["status"] == "succeeded"
    assert by_action_id["action_2"]["result"]["recipients"] == ["adarsh@example.com"]
    assert by_action_id["action_2"]["result"]["message_id"] == "msg_1"


def test_calendar_succeeds_and_email_fails_reports_partially_executed(configured_settings):
    fake_client = PerUrlFakeN8nClient(
        responses={
            CALENDAR_WEBHOOK_URL: {"success": True, "external_event_id": "evt_1", "html_link": "https://cal/evt_1"},
            EMAIL_WEBHOOK_URL: {"success": False, "error_code": "SMTP_AUTH_FAILED", "message": "bad credentials"},
        }
    )
    n8n_client.set_n8n_client(fake_client)
    plan_id = _create_and_approve_plan(CALENDAR_AND_SEND_EMAIL_RAW_PLAN, text=CALENDAR_AND_SEND_EMAIL_TEXT)

    response = client.post(f"/api/v1/plans/{plan_id}/execute")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partially_executed"
    assert body["execution"]["status"] == "partial"

    by_action_id = {a["action_id"]: a for a in body["execution"]["actions"]}
    assert by_action_id["action_1"]["status"] == "succeeded"
    assert by_action_id["action_2"]["status"] == "failed"
    assert by_action_id["action_2"]["error"]["code"] == "SMTP_AUTH_FAILED"


def test_calendar_fails_and_email_succeeds_reports_partially_executed(configured_settings):
    # The reverse of the above - order of actions in a plan never determines
    # which one succeeds; each is dispatched to its own adapter independently.
    fake_client = PerUrlFakeN8nClient(
        responses={
            CALENDAR_WEBHOOK_URL: {"success": False, "error_code": "CALENDAR_API_ERROR", "message": "quota exceeded"},
            EMAIL_WEBHOOK_URL: {"success": True, "message_id": "msg_1"},
        }
    )
    n8n_client.set_n8n_client(fake_client)
    plan_id = _create_and_approve_plan(CALENDAR_AND_SEND_EMAIL_RAW_PLAN, text=CALENDAR_AND_SEND_EMAIL_TEXT)

    response = client.post(f"/api/v1/plans/{plan_id}/execute")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partially_executed"
    assert body["execution"]["status"] == "partial"

    by_action_id = {a["action_id"]: a for a in body["execution"]["actions"]}
    assert by_action_id["action_1"]["status"] == "failed"
    assert by_action_id["action_1"]["error"]["code"] == "CALENDAR_API_ERROR"
    assert by_action_id["action_2"]["status"] == "succeeded"
    assert by_action_id["action_2"]["result"]["message_id"] == "msg_1"


def test_calendar_and_email_both_fail_reports_execution_failed(configured_settings):
    fake_client = PerUrlFakeN8nClient(
        responses={
            CALENDAR_WEBHOOK_URL: {"success": False, "error_code": "CALENDAR_API_ERROR", "message": "quota exceeded"},
            EMAIL_WEBHOOK_URL: {"success": False, "error_code": "SMTP_AUTH_FAILED", "message": "bad credentials"},
        }
    )
    n8n_client.set_n8n_client(fake_client)
    plan_id = _create_and_approve_plan(CALENDAR_AND_SEND_EMAIL_RAW_PLAN, text=CALENDAR_AND_SEND_EMAIL_TEXT)

    response = client.post(f"/api/v1/plans/{plan_id}/execute")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "execution_failed"
    assert body["execution"]["status"] == "failed"

    by_action_id = {a["action_id"]: a for a in body["execution"]["actions"]}
    assert by_action_id["action_1"]["status"] == "failed"
    assert by_action_id["action_1"]["error"]["code"] == "CALENDAR_API_ERROR"
    assert by_action_id["action_2"]["status"] == "failed"
    assert by_action_id["action_2"]["error"]["code"] == "SMTP_AUTH_FAILED"
    # Both results are preserved independently - a double failure is never
    # collapsed into one generic error.
    assert len(body["execution"]["actions"]) == 2


def test_retry_after_email_failure_only_recalls_the_email_webhook_not_calendar(configured_settings):
    fake_client = PerUrlFakeN8nClient(
        responses={
            CALENDAR_WEBHOOK_URL: {"success": True, "external_event_id": "evt_1", "html_link": "https://cal/evt_1"},
            EMAIL_WEBHOOK_URL: {"success": False, "error_code": "SMTP_AUTH_FAILED", "message": "bad credentials"},
        }
    )
    n8n_client.set_n8n_client(fake_client)
    plan_id = _create_and_approve_plan(CALENDAR_AND_SEND_EMAIL_RAW_PLAN, text=CALENDAR_AND_SEND_EMAIL_TEXT)

    first = client.post(f"/api/v1/plans/{plan_id}/execute")
    assert first.status_code == 200
    assert first.json()["status"] == "partially_executed"
    assert len(fake_client.calls_to(CALENDAR_WEBHOOK_URL)) == 1
    assert len(fake_client.calls_to(EMAIL_WEBHOOK_URL)) == 1

    # Fix the email side (e.g. the SMTP credential), then retry the SAME plan.
    fake_client.responses[EMAIL_WEBHOOK_URL] = {"success": True, "message_id": "msg_1"}

    second = client.post(f"/api/v1/plans/{plan_id}/execute")
    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "executed"

    # Calendar was NEVER re-dispatched on retry - only the failed email
    # action was.
    assert len(fake_client.calls_to(CALENDAR_WEBHOOK_URL)) == 1
    assert len(fake_client.calls_to(EMAIL_WEBHOOK_URL)) == 2

    by_action_id = {a["action_id"]: a for a in body["execution"]["actions"]}
    assert by_action_id["action_1"]["attempt_count"] == 1
    assert by_action_id["action_1"]["status"] == "succeeded"
    assert by_action_id["action_2"]["attempt_count"] == 2
    assert by_action_id["action_2"]["status"] == "succeeded"


def test_plan_with_unresolved_email_recipient_stays_blocked_from_execution(configured_settings):
    # RESOLVE_RECIPIENTS cannot find "Unknown Team" - the plan is stuck at
    # needs_clarification (never approvable), so /execute is rejected before
    # any adapter or n8n call happens. This is the same protection every
    # other needs_clarification plan gets; nothing email-specific is needed
    # to guarantee it.
    raw_plan = {
        "intent": "productivity_workflow",
        "summary": "Schedule a meeting and email the Unknown Team.",
        "actions": [
            {
                "action_id": "action_1",
                "tool": "calendar",
                "operation": "create_event",
                "parameters": {"title": "AI Team Meeting"},
                "missing_information": [],
            },
            {
                "action_id": "action_2",
                "tool": "email",
                "operation": "send_email",
                "parameters": {"to": "Unknown Team", "subject": "Project Update", "body": "Here is the update."},
                "missing_information": [],
            },
        ],
    }
    created = _create_plan(
        raw_plan,
        text=(
            "Schedule a meeting with the AI team tomorrow at 3 PM and send the Unknown Team "
            "an email about the project update."
        ),
    )
    assert created["status"] == "needs_clarification"

    response = client.post(f"/api/v1/plans/{created['plan_id']}/execute")

    assert response.status_code == 409
    assert response.json()["detail"]["current_status"] == "needs_clarification"
