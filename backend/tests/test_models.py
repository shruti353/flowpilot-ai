import pytest
from pydantic import ValidationError

from app.models.action import Action
from app.models.execution_plan import MAX_ACTIONS_PER_PLAN, ExecutionPlan, PlanStatus
from app.models.request import AgentPlanRequest


def _calendar_action(action_id: str) -> Action:
    return Action(
        action_id=action_id,
        tool="calendar",
        operation="create_event",
        parameters={"title": "AI Team Meeting", "datetime": "tomorrow at 3 PM"},
    )


def test_agent_plan_request_accepts_normal_text():
    request = AgentPlanRequest(text="Schedule a meeting tomorrow at 3 PM.")
    assert request.text == "Schedule a meeting tomorrow at 3 PM."


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_agent_plan_request_rejects_blank_text(blank):
    with pytest.raises(ValidationError):
        AgentPlanRequest(text=blank)


def test_action_accepts_supported_tool_operation_pair():
    action = Action(
        action_id="action_1",
        tool="calendar",
        operation="create_event",
        parameters={"title": "AI Team Meeting", "datetime": "tomorrow at 3 PM"},
    )
    assert action.requires_approval is True
    assert action.missing_information == []


def test_action_rejects_unsupported_tool():
    with pytest.raises(ValidationError):
        Action(action_id="action_1", tool="slack", operation="send_message", parameters={})


def test_action_rejects_operation_not_valid_for_tool():
    with pytest.raises(ValidationError):
        Action(
            action_id="action_1",
            tool="calendar",
            operation="send_email",
            parameters={},
        )


def test_execution_plan_status_ready_when_nothing_missing():
    plan = ExecutionPlan(
        plan_id="plan-1",
        intent="productivity_workflow",
        summary="Create a meeting.",
        actions=[
            Action(
                action_id="action_1",
                tool="calendar",
                operation="create_event",
                parameters={"title": "AI Team Meeting", "datetime": "tomorrow at 3 PM"},
            )
        ],
    )
    assert plan.status == PlanStatus.ready


def test_execution_plan_status_needs_clarification_when_info_missing():
    plan = ExecutionPlan(
        plan_id="plan-1",
        intent="productivity_workflow",
        summary="Create a meeting; the title was not provided.",
        actions=[
            Action(
                action_id="action_1",
                tool="calendar",
                operation="create_event",
                parameters={"datetime": "tomorrow"},
                missing_information=["title"],
            )
        ],
    )
    assert plan.status == PlanStatus.needs_clarification


# --- Week 5: multi-action plans (1-3 actions, ordered, unique ids) ------


@pytest.mark.parametrize("count", [1, 2, 3])
def test_execution_plan_accepts_one_to_three_actions(count):
    actions = [_calendar_action(f"action_{i + 1}") for i in range(count)]
    plan = ExecutionPlan(
        plan_id="plan-1", intent="productivity_workflow", summary="Do things.", actions=actions
    )
    assert len(plan.actions) == count
    # Deterministic ordering: actions come back in exactly the order given.
    assert [a.action_id for a in plan.actions] == [a.action_id for a in actions]


def test_execution_plan_rejects_zero_actions():
    with pytest.raises(ValidationError):
        ExecutionPlan(plan_id="plan-1", intent="productivity_workflow", summary="Nothing.", actions=[])


def test_execution_plan_rejects_more_than_max_actions():
    assert MAX_ACTIONS_PER_PLAN == 3
    actions = [_calendar_action(f"action_{i + 1}") for i in range(MAX_ACTIONS_PER_PLAN + 1)]
    with pytest.raises(ValidationError, match="exceeds the maximum"):
        ExecutionPlan(
            plan_id="plan-1", intent="productivity_workflow", summary="Too many things.", actions=actions
        )


def test_execution_plan_rejects_duplicate_action_ids():
    actions = [_calendar_action("action_1"), _calendar_action("action_1")]
    with pytest.raises(ValidationError, match="unique action_id"):
        ExecutionPlan(
            plan_id="plan-1", intent="productivity_workflow", summary="Duplicated.", actions=actions
        )
