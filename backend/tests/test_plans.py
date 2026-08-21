"""Tests for the Week 2 human-in-the-loop plan lifecycle:
GET /api/v1/plans/{plan_id} and the approve/reject/cancel endpoints.
"""

from fastapi.testclient import TestClient

import app.services.ollama_service as ollama_service
from app.main import app
from tests.conftest import FakeProvider

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

UNSUPPORTED_TOOL_RAW_PLAN = {
    "intent": "unknown",
    "summary": "Post a message to a channel.",
    "actions": [
        {
            "action_id": "action_1",
            "tool": "slack",
            "operation": "send_message",
            "parameters": {},
            "missing_information": [],
        }
    ],
}


def _create_plan(raw_plan: dict, text: str = "irrelevant, provider is mocked") -> dict:
    ollama_service.set_llm_provider(FakeProvider(result=raw_plan))
    response = client.post("/api/v1/agent/plan", json={"text": text})
    assert response.status_code == 200
    return response.json()


def test_generated_plan_is_stored_and_retrievable():
    created = _create_plan(VALID_RAW_PLAN)
    plan_id = created["plan_id"]

    response = client.get(f"/api/v1/plans/{plan_id}")

    assert response.status_code == 200
    stored = response.json()
    assert stored["plan_id"] == plan_id
    assert stored["status"] == "awaiting_approval"
    assert stored["execution_plan"]["intent"] == "productivity_workflow"


def test_valid_plan_can_be_approved():
    created = _create_plan(VALID_RAW_PLAN)
    plan_id = created["plan_id"]

    response = client.post(f"/api/v1/plans/{plan_id}/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["plan"]["status"] == "approved"

    # Approval only changes state - it must be reflected on GET too.
    refetched = client.get(f"/api/v1/plans/{plan_id}").json()
    assert refetched["status"] == "approved"


def test_valid_plan_can_be_rejected_with_reason():
    created = _create_plan(VALID_RAW_PLAN)
    plan_id = created["plan_id"]

    response = client.post(
        f"/api/v1/plans/{plan_id}/reject",
        json={"reason": "I want to change the meeting time."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["rejection_reason"] == "I want to change the meeting time."

    refetched = client.get(f"/api/v1/plans/{plan_id}").json()
    assert refetched["status"] == "rejected"
    assert refetched["rejection_reason"] == "I want to change the meeting time."


def test_plan_can_be_rejected_without_a_reason():
    created = _create_plan(VALID_RAW_PLAN)
    plan_id = created["plan_id"]

    response = client.post(f"/api/v1/plans/{plan_id}/reject")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["rejection_reason"] is None


def test_valid_plan_can_be_cancelled():
    created = _create_plan(VALID_RAW_PLAN)
    plan_id = created["plan_id"]

    response = client.post(f"/api/v1/plans/{plan_id}/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"


def test_plan_with_missing_information_cannot_be_approved():
    created = _create_plan(NEEDS_CLARIFICATION_RAW_PLAN)
    plan_id = created["plan_id"]
    assert created["status"] == "needs_clarification"

    response = client.post(f"/api/v1/plans/{plan_id}/approve")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["current_status"] == "needs_clarification"


def test_error_plan_cannot_be_approved():
    created = _create_plan(UNSUPPORTED_TOOL_RAW_PLAN)
    plan_id = created["plan_id"]
    assert created["status"] == "error"

    response = client.post(f"/api/v1/plans/{plan_id}/approve")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["current_status"] == "error"


def test_already_approved_plan_cannot_be_approved_again():
    created = _create_plan(VALID_RAW_PLAN)
    plan_id = created["plan_id"]

    first = client.post(f"/api/v1/plans/{plan_id}/approve")
    assert first.status_code == 200

    second = client.post(f"/api/v1/plans/{plan_id}/approve")
    assert second.status_code == 409
    assert second.json()["detail"]["current_status"] == "approved"


def test_rejected_plan_cannot_later_be_approved():
    created = _create_plan(VALID_RAW_PLAN)
    plan_id = created["plan_id"]

    reject_response = client.post(f"/api/v1/plans/{plan_id}/reject")
    assert reject_response.status_code == 200

    approve_response = client.post(f"/api/v1/plans/{plan_id}/approve")
    assert approve_response.status_code == 409
    assert approve_response.json()["detail"]["current_status"] == "rejected"


def test_cancelled_plan_cannot_be_rejected_or_approved():
    created = _create_plan(VALID_RAW_PLAN)
    plan_id = created["plan_id"]

    cancel_response = client.post(f"/api/v1/plans/{plan_id}/cancel")
    assert cancel_response.status_code == 200

    assert client.post(f"/api/v1/plans/{plan_id}/approve").status_code == 409
    assert client.post(f"/api/v1/plans/{plan_id}/reject").status_code == 409


def test_unknown_plan_id_returns_404_on_every_endpoint():
    missing_id = "does-not-exist"

    assert client.get(f"/api/v1/plans/{missing_id}").status_code == 404
    assert client.post(f"/api/v1/plans/{missing_id}/approve").status_code == 404
    assert client.post(f"/api/v1/plans/{missing_id}/reject").status_code == 404
    assert client.post(f"/api/v1/plans/{missing_id}/cancel").status_code == 404
