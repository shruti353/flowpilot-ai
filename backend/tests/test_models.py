import pytest
from pydantic import ValidationError

from app.models.action import Action
from app.models.execution_plan import ExecutionPlan, PlanStatus
from app.models.request import AgentPlanRequest


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
