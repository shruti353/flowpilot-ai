"""Regression tests for the FlowPilot <-> n8n email payload contract.

Mirrors tests/test_n8n_workflow_contract.py for the calendar workflow: pins
the exact structural details that must stay in sync between
app.execution.adapters.n8n_email.N8nEmailSendAdapter and
workflows/flowpilot_email.json's "Validate Payload" node, without executing
any JavaScript (no Node runtime in this backend) or needing a live n8n
instance.
"""

import json
from pathlib import Path

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / "workflows" / "flowpilot_email.json"


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
    js_code = _node(_load_workflow(), "Validate Payload")["parameters"]["jsCode"]
    assert "$input.item.json.body" in js_code
    assert "$input.item.json;" not in js_code


def test_validate_payload_reads_the_fields_the_adapter_sends():
    js_code = _node(_load_workflow(), "Validate Payload")["parameters"]["jsCode"]

    # Matches the exact payload shape built in
    # N8nEmailSendAdapter.execute: body.action.{tool,operation},
    # body.action.parameters.{to,subject,body}.
    assert "body.action" in js_code
    assert "action.parameters" in js_code
    assert "action.tool !== 'email'" in js_code
    assert "action.operation !== 'send_email'" in js_code
    assert "params.to" in js_code
    assert "params.subject" in js_code
    assert "params.body" in js_code


def test_validate_payload_rejects_recipients_without_an_at_sign():
    # `to` must already be resolved, real addresses - the workflow itself
    # also refuses to trust anything that doesn't look like an address, as a
    # second line of defense behind app.services.contact_resolution_service.
    js_code = _node(_load_workflow(), "Validate Payload")["parameters"]["jsCode"]
    assert "includes('@')" in js_code


def test_send_email_node_maps_to_subject_text_from_validated_output():
    node = _node(_load_workflow(), "Send Email")
    params = node["parameters"]

    assert params["toEmail"] == "={{ $json.to }}"
    assert params["subject"] == "={{ $json.subject }}"
    assert params["text"] == "={{ $json.text }}"


def test_send_email_node_carries_no_credential_reference_or_secret():
    # No password/API key ever appears inline in the workflow JSON - the SMTP
    # credential is bound by hand inside n8n's own credential store.
    #
    # It also exports with NO credential reference at all: a placeholder
    # credential id (the previous approach) makes the node look configured
    # while failing to resolve at run time, which is exactly how a send that
    # never happened got reported as a success (see the test below).
    node = _node(_load_workflow(), "Send Email")
    assert "credentials" not in node
    assert "password" not in json.dumps(node).lower()


def test_success_response_is_gated_on_proof_that_the_email_was_actually_sent():
    """Regression guard for a false-success bug.

    The Send Email node errored ("Credential ... does not exist"), passed its
    INPUT straight through on output 0, and that output was wired directly to
    "Respond Success" - so the workflow answered {"success": true} for an
    email that was never sent, and the backend faithfully recorded the action
    as succeeded.

    The fix: every Send Email output goes through an IF node that requires a
    real SMTP messageId before "Respond Success" can be reached. Success must
    be proven, never inferred from which branch an item came out of.
    """
    workflow = _load_workflow()
    connections = workflow["connections"]

    gate = _node(workflow, "Verify Send Result")
    assert gate["type"] == "n8n-nodes-base.if"
    condition = gate["parameters"]["conditions"]["conditions"][0]
    assert "messageId" in condition["leftValue"]
    assert condition["operator"]["operation"] == "notEmpty"

    # EVERY Send Email output must land on the gate - never on a Respond node
    # directly - regardless of which output index n8n routes an error to.
    send_targets = {edge["node"] for branch in connections["Send Email"]["main"] for edge in branch}
    assert send_targets == {"Verify Send Result"}

    # Only the gate's true branch may answer success; the false branch must
    # report failure.
    gate_branches = connections["Verify Send Result"]["main"]
    assert [edge["node"] for edge in gate_branches[0]] == ["Respond Success"]
    assert [edge["node"] for edge in gate_branches[1]] == ["Respond Email Failure"]


def test_success_response_reports_the_real_message_id():
    body = _node(_load_workflow(), "Respond Success")["parameters"]["responseBody"]
    assert "$json.messageId" in body
    assert "success: true" in body


def test_webhook_path_matches_configured_email_webhook_path():
    webhook = _node(_load_workflow(), "Webhook")
    assert webhook["parameters"]["path"] == "flowpilot-email"


def test_error_branches_are_wired_to_respond_nodes():
    connections = _load_workflow()["connections"]

    validate_targets = {
        edge["node"] for branch in connections["Validate Payload"]["main"] for edge in branch
    }
    assert "Send Email" in validate_targets
    assert "Respond Invalid Payload" in validate_targets

    gate_targets = {
        edge["node"] for branch in connections["Verify Send Result"]["main"] for edge in branch
    }
    assert "Respond Success" in gate_targets
    assert "Respond Email Failure" in gate_targets
