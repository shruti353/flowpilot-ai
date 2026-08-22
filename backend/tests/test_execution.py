"""Tests for Week 3 approval-gated execution: dispatcher/adapter unit
tests plus the full approve -> execute API flow. All n8n calls are
mocked (FakeN8nClient) - nothing here needs a real n8n server, Google
Calendar credentials, or a real Ollama server.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app.execution.adapters.n8n_calendar as n8n_calendar_module
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

VALID_RAW_PLAN = {
    "intent": "productivity_workflow",
    "summary": "Create a meeting and a preparation task.",
    "actions": [
        {
            "action_id": "action_1",
            "tool": "calendar",
            "operation": "create_event",
            "parameters": {"title": "AI Team Meeting", "datetime": "tomorrow at 3 PM"},
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
            "parameters": {"title": "AI Team Meeting", "datetime": "tomorrow at 3 PM"},
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
            "parameters": {"datetime": "tomorrow"},
            "missing_information": ["title"],
        }
    ],
}


def _create_plan(raw_plan: dict, text: str = "irrelevant, provider is mocked") -> dict:
    ollama_service.set_llm_provider(FakeProvider(result=raw_plan))
    response = client.post("/api/v1/agent/plan", json={"text": text})
    assert response.status_code == 200
    return response.json()


def _create_and_approve_plan(raw_plan: dict = CALENDAR_ONLY_RAW_PLAN) -> str:
    plan_id = _create_plan(raw_plan)["plan_id"]
    approve_response = client.post(f"/api/v1/plans/{plan_id}/approve")
    assert approve_response.status_code == 200
    return plan_id


@pytest.fixture
def configured_settings(monkeypatch):
    settings = Settings(
        n8n_calendar_webhook_url="http://n8n.test/webhook/flowpilot-calendar",
        flowpilot_timezone="Asia/Kolkata",
        default_event_duration_minutes=60,
        n8n_timeout_seconds=5,
    )
    monkeypatch.setattr(n8n_calendar_module, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def unconfigured_settings(monkeypatch):
    settings = Settings(
        n8n_calendar_webhook_url=None,
        n8n_base_url=None,
        flowpilot_timezone="Asia/Kolkata",
        default_event_duration_minutes=60,
        n8n_timeout_seconds=5,
    )
    monkeypatch.setattr(n8n_calendar_module, "get_settings", lambda: settings)
    return settings


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def test_dispatcher_finds_adapter_for_calendar_create_event():
    from app.models.action import OperationName, ToolName

    adapter = get_adapter(ToolName.calendar, OperationName.create_event)
    assert adapter is not None


@pytest.mark.parametrize(
    "tool,operation",
    [
        ("calendar", "get_event"),
        ("tasks", "create_task"),
        ("tasks", "get_task"),
        ("email", "draft_email"),
        ("email", "send_email"),
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
    plan_id = _create_plan(NEEDS_CLARIFICATION_RAW_PLAN)["plan_id"]

    response = client.post(f"/api/v1/plans/{plan_id}/execute")

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
