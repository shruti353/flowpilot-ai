"""Regression tests for the FlowPilot <-> n8n payload contract.

These don't execute the workflow's JavaScript (no Node runtime in this
backend) - they pin the exact structural details that broke integration
before: the n8n Webhook node nests the POST body under `.body`, and the
"Validate Payload" node's field names must match what
app.execution.adapters.n8n_calendar.N8nCalendarCreateEventAdapter actually
sends. If either side changes its field names without the other, these
tests catch it even though no live n8n instance is involved.
"""

import json
from pathlib import Path

WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2] / "workflows" / "flowpilot_google_calendar.json"
)


def _load_workflow() -> dict:
    with open(WORKFLOW_PATH, encoding="utf-8") as f:
        return json.load(f)


def _node(workflow: dict, name: str) -> dict:
    return next(node for node in workflow["nodes"] if node["name"] == name)


def test_workflow_json_is_well_formed():
    workflow = _load_workflow()
    assert workflow["nodes"]
    assert workflow["connections"]


def test_validate_payload_unwraps_the_webhook_body_wrapper():
    # The exact regression this suite guards: n8n's Webhook node always
    # nests the real POST body under `.body`. Reading `$input.item.json`
    # directly (instead of `$input.item.json.body`) silently produces an
    # empty `action`, which used to fail every execution with
    # "The request payload was invalid."
    js_code = _node(_load_workflow(), "Validate Payload")["parameters"]["jsCode"]
    assert "$input.item.json.body" in js_code
    assert "$input.item.json;" not in js_code


def test_validate_payload_reads_the_fields_the_adapter_sends():
    js_code = _node(_load_workflow(), "Validate Payload")["parameters"]["jsCode"]

    # Matches the exact payload shape built in
    # N8nCalendarCreateEventAdapter.execute: body.action.{tool,operation},
    # body.action.parameters.{title,start_datetime,end_datetime,timezone}.
    assert "body.action" in js_code
    assert "action.parameters" in js_code
    assert "action.tool !== 'calendar'" in js_code
    assert "action.operation !== 'create_event'" in js_code
    assert "params.title" in js_code
    assert "params.start_datetime" in js_code
    assert "params.end_datetime" in js_code


def test_google_calendar_node_maps_summary_start_end_from_validated_output():
    node = _node(_load_workflow(), "Create Google Calendar Event")
    params = node["parameters"]

    assert params["start"] == "={{ $json.start_datetime }}"
    assert params["end"] == "={{ $json.end_datetime }}"
    assert params["additionalFields"]["summary"] == "={{ $json.title }}"


def test_webhook_path_matches_configured_calendar_webhook_path():
    webhook = _node(_load_workflow(), "Webhook")
    assert webhook["parameters"]["path"] == "flowpilot-calendar"


def test_error_branches_are_wired_to_respond_nodes():
    connections = _load_workflow()["connections"]

    validate_targets = {
        edge["node"] for branch in connections["Validate Payload"]["main"] for edge in branch
    }
    assert "Create Google Calendar Event" in validate_targets
    assert "Respond Invalid Payload" in validate_targets

    calendar_targets = {
        edge["node"] for branch in connections["Create Google Calendar Event"]["main"] for edge in branch
    }
    assert "Respond Success" in calendar_targets
    assert "Respond Calendar Failure" in calendar_targets
