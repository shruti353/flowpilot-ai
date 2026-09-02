"""Tests for POST /api/v1/agent/plan.

Note: since Week 2, `status` on this endpoint is the stored plan's
lifecycle status ("awaiting_approval" / "needs_clarification" / "error"),
not a generic "success"/"error" flag - see app/models/stored_plan.py.
Plan lifecycle (approve/reject/cancel) tests live in tests/test_plans.py.
"""

from fastapi.testclient import TestClient

import app.services.ollama_service as ollama_service
from app.core.config import get_settings
from app.main import app
from app.services.ollama_service import OllamaServiceError
from app.utils.datetime_parser import normalize_datetime
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


def test_plan_endpoint_infers_title_when_llm_omits_it():
    # Regression: reproduces the exact reported bug. The LLM (like a real
    # Ollama model sometimes does) fails to infer the title itself and
    # flags it as missing, even though "a meeting with the AI team" makes
    # it derivable. The deterministic INFER_TITLES node must fill it in
    # before validation so the plan comes back "ready", not
    # "needs_clarification".
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
    ollama_service.set_llm_provider(FakeProvider(result=raw_plan))

    response = client.post(
        "/api/v1/agent/plan",
        json={"text": "Schedule a meeting with the AI team for tomorrow at 3 PM"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_approval"
    assert body["execution_plan"]["status"] == "ready"
    action = body["execution_plan"]["actions"][0]
    assert action["parameters"]["title"] == "AI Team Meeting"
    assert action["parameters"]["datetime"] == "tomorrow at 3 PM"
    assert action["missing_information"] == []


def test_plan_endpoint_resolves_relative_datetime_alongside_inferred_title():
    # Regression: reproduces the exact reported request end to end. The
    # plan preview must contain a resolved, concrete ISO datetime - not
    # just the raw "tomorrow at 3 PM" expression - alongside the
    # deterministically-inferred title.
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
    ollama_service.set_llm_provider(FakeProvider(result=raw_plan))

    response = client.post(
        "/api/v1/agent/plan",
        json={"text": "Schedule a meeting with the AI team for tomorrow at 3 PM"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_approval"
    assert body["execution_plan"]["status"] == "ready"
    action = body["execution_plan"]["actions"][0]
    assert action["parameters"]["title"] == "AI Team Meeting"
    assert action["parameters"]["datetime"] == "tomorrow at 3 PM"

    expected_resolved = normalize_datetime(
        "tomorrow at 3 PM", get_settings().flowpilot_timezone
    ).isoformat()
    assert action["parameters"]["resolved_datetime"] == expected_resolved
    assert action["parameters"]["resolved_datetime"].endswith("+05:30")


def test_plan_endpoint_does_not_block_on_missing_optional_location():
    # Regression: reproduces the exact reported request end to end. The
    # LLM flagged "location" as missing for calendar.create_event even
    # though it's genuinely optional - the plan must still come back
    # "ready", not "needs_clarification", and title inference / datetime
    # enrichment must be unaffected.
    raw_plan = {
        "intent": "productivity_workflow",
        "summary": "Create a meeting; the title and location were not provided.",
        "actions": [
            {
                "action_id": "action_1",
                "tool": "calendar",
                "operation": "create_event",
                "parameters": {"datetime": "tomorrow at 3 PM"},
                "missing_information": ["title", "location"],
            }
        ],
    }
    ollama_service.set_llm_provider(FakeProvider(result=raw_plan))

    response = client.post(
        "/api/v1/agent/plan",
        json={"text": "Schedule a meeting with AI team for tomorrow at 3 PM"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_approval"
    assert body["execution_plan"]["status"] == "ready"
    action = body["execution_plan"]["actions"][0]
    assert action["missing_information"] == []
    assert action["parameters"]["title"] == "AI Team Meeting"

    expected_resolved = normalize_datetime(
        "tomorrow at 3 PM", get_settings().flowpilot_timezone
    ).isoformat()
    assert action["parameters"]["resolved_datetime"] == expected_resolved
    assert "location" not in action["parameters"]


def test_plan_endpoint_still_needs_clarification_when_title_genuinely_missing():
    raw_plan = {
        "intent": "productivity_workflow",
        "summary": "Create a meeting; the title was not provided.",
        "actions": [
            {
                "action_id": "action_1",
                "tool": "calendar",
                "operation": "create_event",
                "parameters": {"datetime": "tomorrow"},
                "missing_information": ["title", "location"],
            }
        ],
    }
    ollama_service.set_llm_provider(FakeProvider(result=raw_plan))

    response = client.post("/api/v1/agent/plan", json={"text": "Schedule a meeting tomorrow."})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_clarification"
    assert body["execution_plan"]["status"] == "needs_clarification"
    # "location" was dropped as optional; "title" remains genuinely missing.
    assert body["execution_plan"]["actions"][0]["missing_information"] == ["title"]


def test_plan_endpoint_returns_502_when_llm_unreachable():
    ollama_service.set_llm_provider(FakeProvider(error=OllamaServiceError("connection refused")))

    response = client.post("/api/v1/agent/plan", json={"text": "Schedule a meeting."})

    assert response.status_code == 502
