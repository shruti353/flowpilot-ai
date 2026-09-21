"""Tests for the Week 2 human-in-the-loop plan lifecycle:
GET /api/v1/plans/{plan_id} and the approve/reject/cancel endpoints.
"""

from fastapi.testclient import TestClient

import app.services.ollama_service as ollama_service
from app.main import app
from tests.conftest import FakeProvider

client = TestClient(app)

DEFAULT_TEXT = "Schedule a meeting with the AI team tomorrow at 3 PM and create a task to prepare the demo."

# Title and datetime are both given directly, so this fixture resolves to
# "awaiting_approval" regardless of the exact wording of the request text -
# only "tomorrow at 3 PM" (or an equivalent) needs to be present in it for
# ENRICH_DATETIME's deterministic date/time detection to agree.
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

# Title missing, date+time will be resolved deterministically from whatever
# text accompanies this fixture (see NEEDS_CLARIFICATION_TEXT below, chosen
# so title inference does NOT fire, keeping "title" genuinely missing).
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
NEEDS_CLARIFICATION_TEXT = "Schedule a meeting tomorrow at 3 PM."

# Nothing but the tool/operation was determinable; paired with
# MULTIPLE_MISSING_FIELDS_TEXT (no title-inferable phrase, no date/time) so
# title, date, and time all end up missing.
MULTIPLE_MISSING_FIELDS_RAW_PLAN = {
    "intent": "productivity_workflow",
    "summary": "Create a meeting; nothing but the tool/operation was provided.",
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
MULTIPLE_MISSING_FIELDS_TEXT = "Schedule a meeting."

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


def _create_plan(raw_plan: dict, text: str = DEFAULT_TEXT) -> dict:
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
    created = _create_plan(NEEDS_CLARIFICATION_RAW_PLAN, text=NEEDS_CLARIFICATION_TEXT)
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
    assert (
        client.post(
            f"/api/v1/plans/{missing_id}/fields",
            json={"actions": [{"action_id": "action_1", "values": {"title": "x"}}]},
        ).status_code
        == 404
    )


# --- Week 4: POST /plans/{plan_id}/fields ------------------------------


def test_missing_field_is_typed_for_the_frontend():
    created = _create_plan(NEEDS_CLARIFICATION_RAW_PLAN, text=NEEDS_CLARIFICATION_TEXT)
    action = created["execution_plan"]["actions"][0]

    assert action["missing_information"] == ["title"]
    assert action["missing_fields"] == [
        {"field": "title", "label": "Title", "type": "text", "required": True, "options": None, "hint": None}
    ]


def test_supplying_the_last_missing_field_reaches_awaiting_approval():
    created = _create_plan(NEEDS_CLARIFICATION_RAW_PLAN, text=NEEDS_CLARIFICATION_TEXT)
    plan_id = created["plan_id"]

    response = client.post(
        f"/api/v1/plans/{plan_id}/fields",
        json={"actions": [{"action_id": "action_1", "values": {"title": "AI Team Meeting"}}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_approval"
    plan = body["plan"]
    assert plan["plan_id"] == plan_id  # same plan, not a new one
    action = plan["execution_plan"]["actions"][0]
    assert action["parameters"]["title"] == "AI Team Meeting"
    assert action["missing_information"] == []
    assert action["missing_fields"] == []

    # It can now proceed through the normal approval flow, unchanged.
    approve = client.post(f"/api/v1/plans/{plan_id}/approve")
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"


def test_supplying_only_some_missing_fields_stays_in_needs_clarification():
    created = _create_plan(MULTIPLE_MISSING_FIELDS_RAW_PLAN, text=MULTIPLE_MISSING_FIELDS_TEXT)
    plan_id = created["plan_id"]

    response = client.post(
        f"/api/v1/plans/{plan_id}/fields",
        json={"actions": [{"action_id": "action_1", "values": {"title": "AI Team Meeting"}}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_clarification"
    action = body["plan"]["execution_plan"]["actions"][0]
    assert action["parameters"]["title"] == "AI Team Meeting"
    assert action["missing_information"] == ["date", "time"]

    approve = client.post(f"/api/v1/plans/{plan_id}/approve")
    assert approve.status_code == 409


def test_supplying_date_and_time_resolves_it_like_plan_generation_does():
    created = _create_plan(MULTIPLE_MISSING_FIELDS_RAW_PLAN, text=MULTIPLE_MISSING_FIELDS_TEXT)
    plan_id = created["plan_id"]

    response = client.post(
        f"/api/v1/plans/{plan_id}/fields",
        json={
            "actions": [
                {
                    "action_id": "action_1",
                    "values": {"title": "AI Team Meeting", "date": "2026-09-10", "time": "15:00"},
                }
            ]
        },
    )

    assert response.status_code == 200
    action = response.json()["plan"]["execution_plan"]["actions"][0]
    assert action["missing_information"] == []
    assert action["parameters"]["resolved_datetime"].startswith("2026-09-10T15:00")


def test_supplying_only_time_first_leaves_date_missing_until_both_are_given():
    # A request that only gives a date (no time) must keep "time" as its
    # own separate missing field - never silently combined or resolved with
    # a guessed value for the other half - until it's supplied too.
    raw_plan = {
        "intent": "productivity_workflow",
        "summary": "Create a meeting; the exact time was not provided.",
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
    created = _create_plan(raw_plan, text="Schedule a meeting with the AI team on 2026-09-10.")
    plan_id = created["plan_id"]
    action = created["execution_plan"]["actions"][0]
    assert action["missing_information"] == ["time"]
    assert action["parameters"]["resolved_date"] == "2026-09-10"
    assert "resolved_datetime" not in action["parameters"]

    response = client.post(
        f"/api/v1/plans/{plan_id}/fields",
        json={"actions": [{"action_id": "action_1", "values": {"time": "15:00"}}]},
    )

    assert response.status_code == 200
    updated_action = response.json()["plan"]["execution_plan"]["actions"][0]
    assert updated_action["missing_information"] == []
    assert updated_action["parameters"]["resolved_datetime"].startswith("2026-09-10T15:00")


def test_fields_endpoint_rejects_unknown_action_id():
    created = _create_plan(NEEDS_CLARIFICATION_RAW_PLAN, text=NEEDS_CLARIFICATION_TEXT)
    plan_id = created["plan_id"]

    response = client.post(
        f"/api/v1/plans/{plan_id}/fields",
        json={"actions": [{"action_id": "does-not-exist", "values": {"title": "x"}}]},
    )

    assert response.status_code == 404


def test_fields_endpoint_rejects_a_field_that_is_not_missing():
    created = _create_plan(NEEDS_CLARIFICATION_RAW_PLAN, text=NEEDS_CLARIFICATION_TEXT)
    plan_id = created["plan_id"]

    response = client.post(
        f"/api/v1/plans/{plan_id}/fields",
        # "date" was already resolved from the request text ("tomorrow at
        # 3 PM") - it is not in missing_information (only "title" is).
        json={"actions": [{"action_id": "action_1", "values": {"date": "2026-09-10"}}]},
    )

    assert response.status_code == 422


def test_fields_endpoint_rejects_plans_not_awaiting_clarification():
    created = _create_plan(VALID_RAW_PLAN)
    plan_id = created["plan_id"]
    assert created["status"] == "awaiting_approval"

    response = client.post(
        f"/api/v1/plans/{plan_id}/fields",
        json={"actions": [{"action_id": "action_1", "values": {"title": "x"}}]},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["current_status"] == "awaiting_approval"


# --- Bug fix: never infer a date/time the user did not supply ----------
#
# End-to-end (through POST /api/v1/agent/plan) coverage of the reported bug:
# "Schedule a meeting with the AI team." was resolving a fabricated
# "tomorrow" and only asking for Time. Title is always given directly here
# (isolating these cases to date/time behavior only) - INFER_TITLES would
# otherwise also infer it from "meeting with the AI team", which is correct
# but orthogonal to what's being tested.

_NO_DATE_OR_TIME_RAW_PLAN = {
    "intent": "productivity_workflow",
    "summary": "Create a meeting with the AI team.",
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


def test_no_date_or_time_mentioned_leaves_both_missing_and_fabricates_nothing():
    created = _create_plan(_NO_DATE_OR_TIME_RAW_PLAN, text="Schedule a meeting with the AI team.")
    action = created["execution_plan"]["actions"][0]

    assert created["execution_plan"]["status"] == "needs_clarification"
    assert set(action["missing_information"]) == {"date", "time"}
    field_names = {f["field"] for f in action["missing_fields"]}
    assert field_names == {"date", "time"}

    # No fabricated date/time anywhere in the preview - not even a stray key.
    for key in ("date", "time", "datetime", "resolved_date", "resolved_time", "resolved_datetime"):
        assert key not in action["parameters"], f"unexpected fabricated '{key}' in parameters"


def test_time_only_mentioned_leaves_only_date_missing():
    created = _create_plan(
        _NO_DATE_OR_TIME_RAW_PLAN, text="Schedule a meeting with the AI team at 3 PM."
    )
    action = created["execution_plan"]["actions"][0]

    assert created["execution_plan"]["status"] == "needs_clarification"
    assert action["missing_information"] == ["date"]
    assert action["missing_fields"] == [
        {"field": "date", "label": "Date", "type": "date", "required": True, "options": None, "hint": None}
    ]
    assert "date" not in action["parameters"]
    assert "resolved_datetime" not in action["parameters"]
    assert action["parameters"]["resolved_time"].startswith("15:00")


def test_date_only_mentioned_leaves_only_time_missing():
    created = _create_plan(
        _NO_DATE_OR_TIME_RAW_PLAN, text="Schedule a meeting with the AI team tomorrow."
    )
    action = created["execution_plan"]["actions"][0]

    assert created["execution_plan"]["status"] == "needs_clarification"
    assert action["missing_information"] == ["time"]
    assert action["missing_fields"] == [
        {"field": "time", "label": "Time", "type": "time", "required": True, "options": None, "hint": None}
    ]
    assert "time" not in action["parameters"]
    assert "resolved_datetime" not in action["parameters"]
    assert "resolved_date" in action["parameters"]


def test_date_and_time_both_mentioned_leaves_nothing_missing():
    created = _create_plan(
        _NO_DATE_OR_TIME_RAW_PLAN, text="Schedule a meeting with the AI team tomorrow at 3 PM."
    )
    action = created["execution_plan"]["actions"][0]

    assert created["execution_plan"]["status"] == "ready"
    assert action["missing_information"] == []
    assert action["missing_fields"] == []
    assert action["parameters"]["resolved_datetime"].endswith("+05:30")


def test_explicit_absolute_date_and_time_resolve_deterministically():
    created = _create_plan(
        _NO_DATE_OR_TIME_RAW_PLAN,
        text="Schedule a meeting with the AI team on 2026-09-15 at 10:00 AM.",
    )
    action = created["execution_plan"]["actions"][0]

    assert created["execution_plan"]["status"] == "ready"
    assert action["missing_information"] == []
    assert action["parameters"]["resolved_datetime"] == "2026-09-15T10:00:00+05:30"


def test_plan_with_no_date_or_time_can_be_completed_via_fields_and_approved():
    # Full loop for the reported bug: missing date+time -> fill both via the
    # missing-fields endpoint -> revalidate -> awaiting_approval -> approve.
    # Never bypasses approval, and the plan_id never changes.
    created = _create_plan(_NO_DATE_OR_TIME_RAW_PLAN, text="Schedule a meeting with the AI team.")
    plan_id = created["plan_id"]
    assert created["status"] == "needs_clarification"

    response = client.post(
        f"/api/v1/plans/{plan_id}/fields",
        json={
            "actions": [
                {"action_id": "action_1", "values": {"date": "2026-09-15", "time": "10:00"}}
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_approval"
    plan = body["plan"]
    assert plan["plan_id"] == plan_id
    action = plan["execution_plan"]["actions"][0]
    assert action["missing_information"] == []
    assert action["parameters"]["resolved_datetime"] == "2026-09-15T10:00:00+05:30"

    approve = client.post(f"/api/v1/plans/{plan_id}/approve")
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"


# --- Week 5: multi-action plans + contacts/teams recipient resolution ---

MULTI_ACTION_CALENDAR_EMAIL_RAW_PLAN = {
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
MULTI_ACTION_TEXT = (
    "Schedule a meeting with the AI team tomorrow at 3 PM and send them an "
    "email about the project update."
)


def test_two_action_plan_validates_each_action_independently():
    # The team isn't saved yet - action_1 (calendar) has everything it
    # needs; action_2 (email) is missing "to" (unresolved reference) as
    # well as the subject/body the LLM already reported. Missing fields
    # must never bleed between actions.
    created = _create_plan(MULTI_ACTION_CALENDAR_EMAIL_RAW_PLAN, text=MULTI_ACTION_TEXT)

    assert created["status"] == "needs_clarification"
    actions = created["execution_plan"]["actions"]
    assert len(actions) == 2

    calendar_action = actions[0]
    assert calendar_action["missing_information"] == []

    email_action = actions[1]
    assert set(email_action["missing_information"]) == {"to", "subject", "body"}
    assert "No saved team or contact matches" in email_action["missing_field_hints"]["to"]
    # The calendar action's completeness is untouched by the email action's gaps.
    assert "to" not in calendar_action.get("missing_information", [])


def test_three_action_plan_is_accepted():
    raw_plan = {
        "intent": "productivity_workflow",
        "summary": "Three things.",
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
            {
                "action_id": "action_3",
                "tool": "email",
                "operation": "send_email",
                "parameters": {},
                "missing_information": ["to", "subject", "body"],
            },
        ],
    }

    created = _create_plan(raw_plan, text=MULTI_ACTION_TEXT)

    assert created["plan_id"]
    assert len(created["execution_plan"]["actions"]) == 3


def test_more_than_three_actions_is_rejected_deterministically_not_truncated():
    raw_plan = {
        "intent": "productivity_workflow",
        "summary": "Four things.",
        "actions": [
            {
                "action_id": f"action_{i}",
                "tool": "tasks",
                "operation": "create_task",
                "parameters": {"title": f"Task {i}"},
                "missing_information": [],
            }
            for i in range(1, 5)
        ],
    }

    created = _create_plan(raw_plan)

    # Rejected outright (status "error", nothing executable) - never
    # silently truncated to the first 3.
    assert created["status"] == "error"
    assert created["execution_plan"] is None
    assert any("exceeds the maximum" in e["message"] for e in created["errors"])


def test_malformed_plan_missing_actions_key_is_rejected():
    raw_plan = {"intent": "productivity_workflow", "summary": "No actions key at all."}
    created = _create_plan(raw_plan)
    assert created["status"] == "error"


def test_unsupported_action_within_a_multi_action_plan_is_rejected():
    raw_plan = {
        "intent": "productivity_workflow",
        "summary": "One good action, one bad one.",
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
                "tool": "slack",
                "operation": "send_message",
                "parameters": {},
                "missing_information": [],
            },
        ],
    }

    created = _create_plan(raw_plan, text=MULTI_ACTION_TEXT)

    assert created["status"] == "error"
    assert created["execution_plan"] is None


def test_saving_a_team_then_filling_email_fields_reaches_awaiting_approval():
    # Full loop: plan created with an unresolvable "AI Team" reference ->
    # the team is saved via the Contacts/Teams API -> resubmitting the
    # SAME reference through /fields now resolves it -> plan reaches
    # awaiting_approval, same plan_id throughout, approval still required.
    created = _create_plan(MULTI_ACTION_CALENDAR_EMAIL_RAW_PLAN, text=MULTI_ACTION_TEXT)
    plan_id = created["plan_id"]
    assert created["status"] == "needs_clarification"

    team = client.post("/api/v1/teams", json={"name": "AI Team"}).json()
    for name, email in [("Adarsh", "adarsh@example.com"), ("Rahul", "rahul@example.com")]:
        client.post(
            f"/api/v1/teams/{team['id']}/members", json={"name": name, "email": email}
        )

    response = client.post(
        f"/api/v1/plans/{plan_id}/fields",
        json={
            "actions": [
                {
                    "action_id": "action_2",
                    "values": {
                        "to": "AI Team",
                        "subject": "Project update",
                        "body": "Here is the latest status.",
                    },
                }
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_approval"
    plan = body["plan"]
    assert plan["plan_id"] == plan_id  # same plan throughout

    email_action = plan["execution_plan"]["actions"][1]
    assert email_action["missing_information"] == []
    resolved_emails = {r["email"] for r in email_action["parameters"]["resolved_recipients"]}
    assert resolved_emails == {"adarsh@example.com", "rahul@example.com"}

    approve = client.post(f"/api/v1/plans/{plan_id}/approve")
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"


# --- Week 5 Day 3: multi-action validation, action isolation, mixed -----
# valid/invalid actions. Builds on the Week 5 Day 1/2 foundation above
# (multi-action plans, deterministic recipient resolution, the
# missing_fields/fields-update pipeline) - no new architecture, just
# additional coverage proving the existing pipeline already satisfies the
# Day 3 requirements: independent per-action validation, no silently
# dropped actions, and action_id-scoped field updates that never bleed
# into a sibling action.

# Calendar action is fully specified (title, date, time all resolve from
# MULTI_ACTION_TEXT); email action is already fully specified too (a
# direct, literal email address needs no saved contact/team) - so this
# plan reaches "awaiting_approval" the moment it's generated, with BOTH
# actions valid. Used for scenario C ("both actions valid").
BOTH_VALID_RAW_PLAN = {
    "intent": "productivity_workflow",
    "summary": "Schedule a meeting and email a colleague about it.",
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
            "parameters": {
                "to": "someone@example.com",
                "subject": "Project update",
                "body": "Here is the latest status.",
            },
            "missing_information": [],
        },
    ],
}

# Calendar action is missing date/time (MULTI_ACTION_TEXT is not used here
# - no date/time phrase); email action is fully specified via a direct
# email address. Used for scenario B ("email valid + calendar missing
# datetime") and for the calendar-update isolation test.
CALENDAR_MISSING_EMAIL_VALID_RAW_PLAN = {
    "intent": "productivity_workflow",
    "summary": "Schedule a meeting and email a colleague about it.",
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
            "parameters": {
                "to": "someone@example.com",
                "subject": "Project update",
                "body": "Here is the latest status.",
            },
            "missing_information": [],
        },
    ],
}
CALENDAR_MISSING_EMAIL_VALID_TEXT = "Schedule a meeting with the AI team and email someone@example.com about the project."


def test_both_actions_valid_reaches_awaiting_approval_and_is_not_auto_approved():
    # Scenario C: both actions valid on generation. The plan must land in
    # awaiting_approval - never "approved" - until a human explicitly hits
    # POST /approve.
    created = _create_plan(BOTH_VALID_RAW_PLAN, text=MULTI_ACTION_TEXT)

    assert created["status"] == "awaiting_approval"
    assert created["execution_plan"]["status"] == "ready"
    actions = created["execution_plan"]["actions"]
    assert len(actions) == 2
    assert all(a["missing_information"] == [] for a in actions)

    # Re-fetching must show the same not-yet-approved status - generation
    # itself never approves anything.
    refetched = client.get(f"/api/v1/plans/{created['plan_id']}").json()
    assert refetched["status"] == "awaiting_approval"

    approve = client.post(f"/api/v1/plans/{created['plan_id']}/approve")
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"


def test_calendar_missing_datetime_with_valid_email_preserves_both_actions():
    # Scenario B: email action is valid, calendar action is missing
    # date/time. Both actions must survive, only the calendar action may
    # be reported as missing information, and the plan overall requires
    # clarification (never silently dropping the email action).
    created = _create_plan(
        CALENDAR_MISSING_EMAIL_VALID_RAW_PLAN, text=CALENDAR_MISSING_EMAIL_VALID_TEXT
    )

    assert created["status"] == "needs_clarification"
    actions = created["execution_plan"]["actions"]
    assert len(actions) == 2

    calendar_action, email_action = actions
    assert set(calendar_action["missing_information"]) == {"date", "time"}
    assert email_action["missing_information"] == []
    assert email_action["parameters"]["resolved_recipients"][0]["email"] == "someone@example.com"

    # A plan with any action missing required information cannot be approved.
    response = client.post(f"/api/v1/plans/{created['plan_id']}/approve")
    assert response.status_code == 409


def test_updating_only_the_email_action_leaves_the_calendar_action_untouched():
    # Action isolation, direction 1: submitting fields scoped to the email
    # action_id must not mutate the calendar action's parameters,
    # missing_information, or missing_fields in any way.
    created = _create_plan(MULTI_ACTION_CALENDAR_EMAIL_RAW_PLAN, text=MULTI_ACTION_TEXT)
    plan_id = created["plan_id"]
    calendar_action_before = created["execution_plan"]["actions"][0]
    assert calendar_action_before["tool"] == "calendar"
    assert calendar_action_before["missing_information"] == []

    response = client.post(
        f"/api/v1/plans/{plan_id}/fields",
        json={
            "actions": [
                {
                    "action_id": "action_2",
                    "values": {
                        "to": "someone@example.com",
                        "subject": "Project update",
                        "body": "Here is the latest status.",
                    },
                }
            ]
        },
    )

    assert response.status_code == 200
    plan = response.json()["plan"]
    calendar_action_after = plan["execution_plan"]["actions"][0]
    assert calendar_action_after == calendar_action_before

    email_action_after = plan["execution_plan"]["actions"][1]
    assert email_action_after["missing_information"] == []
    assert email_action_after["parameters"]["resolved_recipients"][0]["email"] == "someone@example.com"


def test_updating_only_the_calendar_action_leaves_the_email_action_untouched():
    # Action isolation, direction 2: submitting fields scoped to the
    # calendar action_id must not mutate the already-valid email action.
    created = _create_plan(
        CALENDAR_MISSING_EMAIL_VALID_RAW_PLAN, text=CALENDAR_MISSING_EMAIL_VALID_TEXT
    )
    plan_id = created["plan_id"]
    email_action_before = created["execution_plan"]["actions"][1]
    assert email_action_before["tool"] == "email"
    assert email_action_before["missing_information"] == []

    response = client.post(
        f"/api/v1/plans/{plan_id}/fields",
        json={
            "actions": [
                {"action_id": "action_1", "values": {"date": "2026-09-10", "time": "15:00"}}
            ]
        },
    )

    assert response.status_code == 200
    plan = response.json()["plan"]
    email_action_after = plan["execution_plan"]["actions"][1]
    assert email_action_after == email_action_before

    calendar_action_after = plan["execution_plan"]["actions"][0]
    assert calendar_action_after["missing_information"] == []
    assert calendar_action_after["parameters"]["resolved_datetime"].startswith("2026-09-10T15:00")

    approve = client.post(f"/api/v1/plans/{plan_id}/approve")
    assert approve.status_code == 200


def test_known_multi_member_team_resolves_at_initial_plan_generation():
    # Scenario E, exercised end-to-end (not just at the resolution-service
    # unit level): when the team already exists with members BEFORE the
    # plan is ever generated, the email action needs no /fields round trip
    # at all - RESOLVE_RECIPIENTS resolves it deterministically during
    # GENERATE_PLAN itself.
    team = client.post("/api/v1/teams", json={"name": "AI Team"}).json()
    for name, email in [("Adarsh", "adarsh@example.com"), ("Rahul", "rahul@example.com")]:
        client.post(f"/api/v1/teams/{team['id']}/members", json={"name": name, "email": email})

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
                "parameters": {
                    "to": "AI Team",
                    "subject": "Project update",
                    "body": "Here is the latest status.",
                },
                "missing_information": [],
            },
        ],
    }

    created = _create_plan(raw_plan, text=MULTI_ACTION_TEXT)

    assert created["status"] == "awaiting_approval"
    email_action = created["execution_plan"]["actions"][1]
    assert email_action["missing_information"] == []
    resolved_emails = {r["email"] for r in email_action["parameters"]["resolved_recipients"]}
    assert resolved_emails == {"adarsh@example.com", "rahul@example.com"}

    approve = client.post(f"/api/v1/plans/{created['plan_id']}/approve")
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"


def test_ambiguous_contact_name_is_unresolved_until_disambiguated_via_fields():
    # Scenario F, end-to-end: two saved contacts share the name "Rahul".
    # The planner must never guess between them - the email action stays
    # missing "to" with a hint explaining the ambiguity, and only a more
    # specific reference (here, a direct email address) resolves it.
    client.post("/api/v1/contacts", json={"name": "Rahul", "email": "rahul.one@example.com"})
    client.post("/api/v1/contacts", json={"name": "Rahul", "email": "rahul.two@example.com"})

    raw_plan = {
        "intent": "productivity_workflow",
        "summary": "Schedule a meeting and email Rahul.",
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
                "parameters": {"to": "Rahul", "subject": "Project update", "body": "Status update."},
                "missing_information": [],
            },
        ],
    }
    created = _create_plan(raw_plan, text=MULTI_ACTION_TEXT)

    assert created["status"] == "needs_clarification"
    calendar_action, email_action = created["execution_plan"]["actions"]
    assert calendar_action["missing_information"] == []
    assert email_action["missing_information"] == ["to"]
    assert "Multiple contacts" in email_action["missing_field_hints"]["to"]
    # No fabricated address anywhere in the preview.
    assert "resolved_recipients" not in email_action["parameters"]

    response = client.post(
        f"/api/v1/plans/{created['plan_id']}/fields",
        json={"actions": [{"action_id": "action_2", "values": {"to": "rahul.two@example.com"}}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_approval"
    updated_email_action = body["plan"]["execution_plan"]["actions"][1]
    assert updated_email_action["missing_information"] == []
    assert updated_email_action["parameters"]["resolved_recipients"][0]["email"] == "rahul.two@example.com"


def test_duplicate_action_ids_rejected_through_the_full_agent_plan_api():
    # Model-level uniqueness (app/models/execution_plan.py) is already unit
    # tested; this pins the same guarantee end-to-end through POST
    # /api/v1/agent/plan - a plan is never silently accepted (or silently
    # de-duplicated) when the LLM emits a repeated action_id.
    raw_plan = {
        "intent": "productivity_workflow",
        "summary": "Schedule a meeting and email about it.",
        "actions": [
            {
                "action_id": "action_1",
                "tool": "calendar",
                "operation": "create_event",
                "parameters": {"title": "AI Team Meeting"},
                "missing_information": [],
            },
            {
                "action_id": "action_1",  # duplicate on purpose
                "tool": "email",
                "operation": "send_email",
                "parameters": {
                    "to": "someone@example.com",
                    "subject": "Project update",
                    "body": "Here is the latest status.",
                },
                "missing_information": [],
            },
        ],
    }

    created = _create_plan(raw_plan, text=MULTI_ACTION_TEXT)

    assert created["status"] == "error"
    assert created["execution_plan"] is None
    assert any("unique" in e["message"] for e in created["errors"])
