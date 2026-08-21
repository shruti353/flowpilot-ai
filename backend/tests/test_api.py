"""Tests for POST /api/v1/agent/plan.

Note: since Week 2, `status` on this endpoint is the stored plan's
lifecycle status ("awaiting_approval" / "needs_clarification" / "error"),
not a generic "success"/"error" flag - see app/models/stored_plan.py.
Plan lifecycle (approve/reject/cancel) tests live in tests/test_plans.py.
"""

from fastapi.testclient import TestClient

import app.services.ollama_service as ollama_service
from app.main import app
from app.services.ollama_service import OllamaServiceError
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


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_plan_endpoint_rejects_blank_text():
    response = client.post("/api/v1/agent/plan", json={"text": "   "})
    assert response.status_code == 422


def test_plan_endpoint_rejects_missing_text_field():
    response = client.post("/api/v1/agent/plan", json={})
    assert response.status_code == 422


def test_plan_endpoint_returns_valid_multi_action_plan():
    ollama_service.set_llm_provider(FakeProvider(result=VALID_RAW_PLAN))

    response = client.post(
        "/api/v1/agent/plan",
        json={"text": "Schedule a meeting with my AI team tomorrow at 3 PM and create a task to prepare the demo."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_approval"
    assert body["execution_plan"]["status"] == "ready"
    assert len(body["execution_plan"]["actions"]) == 2
    assert body["request_id"]
    assert body["plan_id"]


def test_plan_endpoint_returns_structured_error_for_unsupported_tool():
    raw_plan = {
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
    ollama_service.set_llm_provider(FakeProvider(result=raw_plan))

    response = client.post("/api/v1/agent/plan", json={"text": "Post 'hi' in #general."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["execution_plan"] is None
    assert body["errors"]
    # Even a failed generation is stored (as "error") so it has a plan_id
    # and is traceable/retrievable via GET /plans/{plan_id}.
    assert body["plan_id"]


def test_plan_endpoint_flags_missing_critical_information():
    raw_plan = {
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
    ollama_service.set_llm_provider(FakeProvider(result=raw_plan))

    response = client.post("/api/v1/agent/plan", json={"text": "Schedule a meeting tomorrow."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_clarification"
    assert body["execution_plan"]["status"] == "needs_clarification"
    assert body["execution_plan"]["actions"][0]["missing_information"] == ["title"]
    assert body["plan_id"]


def test_plan_endpoint_returns_502_when_llm_unreachable():
    ollama_service.set_llm_provider(FakeProvider(error=OllamaServiceError("connection refused")))

    response = client.post("/api/v1/agent/plan", json={"text": "Schedule a meeting."})

    assert response.status_code == 502
