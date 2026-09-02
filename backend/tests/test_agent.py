import pytest

import app.services.ollama_service as ollama_service
from app.agent.nodes.enrich_datetime import enrich_datetime
from app.agent.nodes.filter_optional_fields import filter_optional_fields
from app.agent.nodes.infer_titles import infer_titles
from app.agent.nodes.plan import generate_plan
from app.agent.nodes.understand import understand_request
from app.agent.nodes.validate import validate_plan
from app.agent.state import initial_state
from app.core.config import get_settings
from app.services.ollama_service import OllamaServiceError
from app.utils.datetime_parser import normalize_datetime
from tests.conftest import FakeProvider

TZ = get_settings().flowpilot_timezone

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


def _calendar_state(user_text: str, raw_datetime: str, *, extra_parameters: dict | None = None):
    state = initial_state("req-1", user_text)
    state["raw_plan"] = {
        "intent": "productivity_workflow",
        "summary": "Create a meeting.",
        "actions": [
            {
                "action_id": "action_1",
                "tool": "calendar",
                "operation": "create_event",
                "parameters": {"datetime": raw_datetime, **(extra_parameters or {})},
                "missing_information": [],
            }
        ],
    }
    return state


def test_enrich_datetime_resolves_tomorrow_at_3pm():
    state = _calendar_state("Schedule a meeting with the AI team for tomorrow at 3 PM", "tomorrow at 3 PM")

    result = enrich_datetime(state)
    action = result["raw_plan"]["actions"][0]

    expected = normalize_datetime("tomorrow at 3 PM", TZ)
    assert action["parameters"]["datetime"] == "tomorrow at 3 PM"
    assert action["parameters"]["resolved_datetime"] == expected.isoformat()


def test_enrich_datetime_resolves_today_at_5pm():
    state = _calendar_state("Schedule a meeting today at 5 PM", "today at 5 PM")

    result = enrich_datetime(state)
    action = result["raw_plan"]["actions"][0]

    expected = normalize_datetime("today at 5 PM", TZ)
    assert action["parameters"]["resolved_datetime"] == expected.isoformat()


def test_enrich_datetime_resolves_a_specific_date_and_time():
    state = _calendar_state("Schedule a meeting on March 10, 2027 at 9 AM", "March 10, 2027 at 9 AM")

    result = enrich_datetime(state)
    action = result["raw_plan"]["actions"][0]

    resolved = action["parameters"]["resolved_datetime"]
    assert resolved.startswith("2027-03-10T09:00:00")


def test_enrich_datetime_uses_correct_timezone_offset():
    state = _calendar_state("Schedule a meeting tomorrow at 3 PM", "tomorrow at 3 PM")

    result = enrich_datetime(state)
    action = result["raw_plan"]["actions"][0]

    # Asia/Kolkata is a fixed +05:30 offset (no DST).
    assert action["parameters"]["resolved_datetime"].endswith("+05:30")


def test_enrich_datetime_does_not_recompute_existing_resolved_datetime():
    state = _calendar_state(
        "Schedule a meeting tomorrow at 3 PM",
        "tomorrow at 3 PM",
        extra_parameters={"resolved_datetime": "2099-01-01T00:00:00+05:30"},
    )

    result = enrich_datetime(state)
    action = result["raw_plan"]["actions"][0]

    assert action["parameters"]["resolved_datetime"] == "2099-01-01T00:00:00+05:30"


def test_enrich_datetime_does_not_invent_datetime_when_missing():
    state = initial_state("req-1", "Schedule a meeting")
    state["raw_plan"] = {
        "intent": "productivity_workflow",
        "summary": "Create a meeting; the time was not provided.",
        "actions": [
            {
                "action_id": "action_1",
                "tool": "calendar",
                "operation": "create_event",
                "parameters": {"title": "Team Sync"},
                "missing_information": ["datetime"],
            }
        ],
    }

    result = enrich_datetime(state)
    action = result["raw_plan"]["actions"][0]

    assert "resolved_datetime" not in action["parameters"]
    assert action["missing_information"] == ["datetime"]


def test_enrich_datetime_ignores_non_calendar_actions():
    state = initial_state("req-1", "Create a task for tomorrow at 3 PM")
    state["raw_plan"] = {
        "intent": "productivity_workflow",
        "summary": "Create a task.",
        "actions": [
            {
                "action_id": "action_1",
                "tool": "tasks",
                "operation": "create_task",
                "parameters": {"title": "Follow up", "datetime": "tomorrow at 3 PM"},
                "missing_information": [],
            }
        ],
    }

    result = enrich_datetime(state)
    action = result["raw_plan"]["actions"][0]

    assert "resolved_datetime" not in action["parameters"]


def test_enrich_datetime_short_circuits_on_prior_error():
    state = _calendar_state("Schedule a meeting tomorrow at 3 PM", "tomorrow at 3 PM")
    state["errors"].append("boom")

    result = enrich_datetime(state)
    action = result["raw_plan"]["actions"][0]

    assert "resolved_datetime" not in action["parameters"]


def test_infer_titles_then_enrich_datetime_together():
    # Regression: reproduces the exact reported request end to end through
    # both deterministic enrichment nodes, as the graph now runs them.
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
    state = enrich_datetime(state)
    result = validate_plan(state)
    action = result["execution_plan"].actions[0]

    expected_resolved = normalize_datetime("tomorrow at 3 PM", TZ).isoformat()
    assert result["execution_plan"].status.value == "ready"
    assert action.parameters["title"] == "AI Team Meeting"
    assert action.parameters["datetime"] == "tomorrow at 3 PM"
    assert action.parameters["resolved_datetime"] == expected_resolved


def test_filter_optional_fields_removes_location_for_calendar_create_event():
    state = initial_state("req-1", "Schedule a meeting with the AI team for tomorrow at 3 PM")
    state["raw_plan"] = {
        "intent": "productivity_workflow",
        "summary": "Create a meeting.",
        "actions": [
            {
                "action_id": "action_1",
                "tool": "calendar",
                "operation": "create_event",
                "parameters": {"title": "AI Team Meeting", "datetime": "tomorrow at 3 PM"},
                "missing_information": ["location"],
            }
        ],
    }

    result = filter_optional_fields(state)
    action = result["raw_plan"]["actions"][0]

    assert action["missing_information"] == []


def test_filter_optional_fields_preserves_genuinely_required_missing_fields():
    state = initial_state("req-1", "Schedule a meeting")
    state["raw_plan"] = {
        "intent": "productivity_workflow",
        "summary": "Create a meeting; title and time were not provided.",
        "actions": [
            {
                "action_id": "action_1",
                "tool": "calendar",
                "operation": "create_event",
                "parameters": {},
                "missing_information": ["title", "datetime", "location"],
            }
        ],
    }

    result = filter_optional_fields(state)
    action = result["raw_plan"]["actions"][0]

    assert set(action["missing_information"]) == {"title", "datetime"}


def test_filter_optional_fields_ignores_non_calendar_actions():
    state = initial_state("req-1", "Create a task")
    state["raw_plan"] = {
        "intent": "productivity_workflow",
        "summary": "Create a task; no due date given.",
        "actions": [
            {
                "action_id": "action_1",
                "tool": "tasks",
                "operation": "create_task",
                "parameters": {"title": "Follow up"},
                "missing_information": ["location"],
            }
        ],
    }

    result = filter_optional_fields(state)
    action = result["raw_plan"]["actions"][0]

    # "location" isn't in the optional-fields registry for tasks.create_task,
    # so it's left untouched - this node only ever narrows what it knows about.
    assert action["missing_information"] == ["location"]


def test_filter_optional_fields_short_circuits_on_prior_error():
    state = initial_state("req-1", "Schedule a meeting with the AI team for tomorrow at 3 PM")
    state["errors"].append("boom")
    state["raw_plan"] = {
        "intent": "productivity_workflow",
        "summary": "irrelevant",
        "actions": [
            {
                "action_id": "action_1",
                "tool": "calendar",
                "operation": "create_event",
                "parameters": {"title": "AI Team Meeting", "datetime": "tomorrow at 3 PM"},
                "missing_information": ["location"],
            }
        ],
    }

    result = filter_optional_fields(state)
    action = result["raw_plan"]["actions"][0]

    assert action["missing_information"] == ["location"]


def test_full_deterministic_chain_reaches_ready_despite_missing_location():
    # Regression: reproduces the exact reported request end to end through
    # every deterministic enrichment node in the order the graph now runs
    # them - title inference and datetime enrichment must keep working
    # exactly as before, and an LLM-flagged-but-optional "location" must
    # no longer block the plan.
    state = initial_state("req-1", "Schedule a meeting with AI team for tomorrow at 3 PM")
    state["raw_plan"] = {
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

    state = infer_titles(state)
    state = enrich_datetime(state)
    state = filter_optional_fields(state)
    result = validate_plan(state)
    action = result["execution_plan"].actions[0]

    expected_resolved = normalize_datetime("tomorrow at 3 PM", TZ).isoformat()
    assert result["execution_plan"].status.value == "ready"
    assert action.missing_information == []
    assert action.parameters["title"] == "AI Team Meeting"
    assert action.parameters["resolved_datetime"] == expected_resolved
    assert "location" not in action.parameters
