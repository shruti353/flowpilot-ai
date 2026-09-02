import pytest

import app.services.ollama_service as ollama_service
from app.agent.nodes.infer_titles import infer_titles
from app.agent.nodes.plan import generate_plan
from app.agent.nodes.understand import understand_request
from app.agent.nodes.validate import validate_plan
from app.agent.state import initial_state
from app.services.ollama_service import OllamaServiceError
from tests.conftest import FakeProvider

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


def test_understand_request_trims_whitespace():
    state = initial_state("req-1", "  Schedule a meeting  ")
    result = understand_request(state)
    assert result["user_text"] == "Schedule a meeting"
    assert result["status"] == "understood"


def test_understand_request_short_circuits_on_prior_error():
    state = initial_state("req-1", "text")
    state["errors"].append("boom")
    result = understand_request(state)
    assert result["status"] != "understood"


@pytest.mark.asyncio
async def test_generate_plan_success():
    ollama_service.set_llm_provider(FakeProvider(result=VALID_RAW_PLAN))
    state = initial_state("req-1", "Schedule a meeting with my AI team tomorrow at 3 PM.")

    result = await generate_plan(state)

    assert result["status"] == "plan_generated"
    assert result["raw_plan"] == VALID_RAW_PLAN
    assert result["intent"] == "productivity_workflow"


@pytest.mark.asyncio
async def test_generate_plan_handles_llm_error():
    ollama_service.set_llm_provider(FakeProvider(error=OllamaServiceError("connection refused")))
    state = initial_state("req-1", "Schedule a meeting.")

    result = await generate_plan(state)

    assert result["status"] == "llm_error"
    assert "connection refused" in result["errors"][-1]


def test_validate_plan_success_multi_action():
    state = initial_state("req-1", "irrelevant")
    state["raw_plan"] = VALID_RAW_PLAN

    result = validate_plan(state)

    assert result["status"] == "validated"
    assert result["execution_plan"] is not None
    assert len(result["execution_plan"].actions) == 2
    assert result["execution_plan"].status.value == "ready"


def test_validate_plan_rejects_unsupported_tool():
    state = initial_state("req-1", "irrelevant")
    state["raw_plan"] = {
        "intent": "unknown",
        "summary": "Post a message.",
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

    result = validate_plan(state)

    assert result["status"] == "validation_failed"
    assert result["execution_plan"] is None
    assert result["validation_errors"]


def test_validate_plan_flags_missing_information():
    state = initial_state("req-1", "irrelevant")
    state["raw_plan"] = {
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

    result = validate_plan(state)

    assert result["status"] == "validated"
    assert result["execution_plan"].status.value == "needs_clarification"


def test_validate_plan_rejects_non_dict_raw_plan():
    state = initial_state("req-1", "irrelevant")
    state["raw_plan"] = "not a json object"

    result = validate_plan(state)

    assert result["status"] == "validation_failed"
    assert result["validation_errors"]


def test_infer_titles_fills_in_title_and_clears_missing_information():
    # Regression: the LLM flagged "title" as missing even though the user's
    # own wording ("a meeting with the AI team") makes it derivable.
    state = initial_state("req-1", "Schedule a meeting with the AI team for tomorrow at 3 PM")
    state["raw_plan"] = {
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

    result = infer_titles(state)
    action = result["raw_plan"]["actions"][0]

    assert action["parameters"]["title"] == "AI Team Meeting"
    assert action["parameters"]["datetime"] == "tomorrow at 3 PM"
    assert action["missing_information"] == []


def test_infer_titles_then_validate_plan_produces_ready_status():
    # End-to-end (minus the LLM call) reproduction of the reported bug: the
    # final ExecutionPlan must be "ready", not "needs_clarification".
    state = initial_state("req-1", "Schedule a meeting with the AI team for tomorrow at 3 PM")
    state["raw_plan"] = {
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

    state = infer_titles(state)
    result = validate_plan(state)

    assert result["execution_plan"].status.value == "ready"
    assert result["execution_plan"].actions[0].parameters["title"] == "AI Team Meeting"


def test_infer_titles_does_not_invent_title_when_unrecognizable():
    state = initial_state("req-1", "Schedule a meeting tomorrow.")
    state["raw_plan"] = {
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

    result = infer_titles(state)
    action = result["raw_plan"]["actions"][0]

    assert "title" not in action["parameters"]
    assert action["missing_information"] == ["title"]


def test_infer_titles_ignores_non_calendar_actions():
    state = initial_state("req-1", "Create a task meeting notes")
    state["raw_plan"] = {
        "intent": "productivity_workflow",
        "summary": "Create a task.",
        "actions": [
            {
                "action_id": "action_1",
                "tool": "tasks",
                "operation": "create_task",
                "parameters": {},
                "missing_information": ["title"],
            }
        ],
    }

    result = infer_titles(state)
    action = result["raw_plan"]["actions"][0]

    assert "title" not in action["parameters"]
    assert action["missing_information"] == ["title"]


def test_infer_titles_does_not_override_existing_title():
    state = initial_state("req-1", "Schedule a meeting with the AI team tomorrow at 3 PM")
    state["raw_plan"] = {
        "intent": "productivity_workflow",
        "summary": "Create a meeting.",
        "actions": [
            {
                "action_id": "action_1",
                "tool": "calendar",
                "operation": "create_event",
                "parameters": {"title": "Weekly Sync", "datetime": "tomorrow at 3 PM"},
                "missing_information": [],
            }
        ],
    }

    result = infer_titles(state)
    action = result["raw_plan"]["actions"][0]

    assert action["parameters"]["title"] == "Weekly Sync"


def test_infer_titles_short_circuits_on_prior_error():
    state = initial_state("req-1", "Schedule a meeting with the AI team tomorrow at 3 PM")
    state["errors"].append("boom")
    state["raw_plan"] = {
        "intent": "productivity_workflow",
        "summary": "irrelevant",
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

    result = infer_titles(state)
    action = result["raw_plan"]["actions"][0]

    assert "title" not in action["parameters"]
