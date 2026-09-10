"""Deterministic (tool, operation, field name) -> input-control mapping.

This is the ONLY place that decides what kind of control a missing field
needs. It mirrors the "typical parameters per operation" list the LLM is
taught in app/prompts/planner_prompt.py, plus a couple of field names the
LLM's own few-shot examples use ("time") that aren't literal parameter keys.
A field name with no entry here (for its operation, or globally) falls back
to a plain text field - never a hard failure, since a text box can always
stand in for any value.

Lives in app/models (not app/agent) because it is schema metadata consumed
directly by the Action model below, not agent/LangGraph orchestration logic.
"""

from app.models.missing_field import FieldType

FieldMeta = tuple[str, FieldType, tuple[str, ...] | None]

#: Per-operation known fields: field_name -> (label, type, options).
_OPERATION_FIELDS: dict[tuple[str, str], dict[str, FieldMeta]] = {
    ("calendar", "create_event"): {
        "title": ("Title", FieldType.text, None),
        "date": ("Date", FieldType.date, None),
        "time": ("Time", FieldType.time, None),
        "attendees": ("Attendees", FieldType.text, None),
        "location": ("Location", FieldType.text, None),
    },
    ("calendar", "get_event"): {
        "title": ("Title", FieldType.text, None),
        "datetime": ("Date & Time", FieldType.datetime, None),
    },
    ("tasks", "create_task"): {
        "title": ("Title", FieldType.text, None),
        "due_date": ("Due Date", FieldType.date, None),
    },
    ("tasks", "get_task"): {
        "title": ("Title", FieldType.text, None),
    },
    ("email", "draft_email"): {
        "to": ("To", FieldType.text, None),
        "subject": ("Subject", FieldType.text, None),
        "body": ("Body", FieldType.text, None),
    },
    ("email", "send_email"): {
        "to": ("To", FieldType.text, None),
        "subject": ("Subject", FieldType.text, None),
        "body": ("Body", FieldType.text, None),
    },
    ("email", "search_email"): {
        "query": ("Search Query", FieldType.text, None),
    },
}

#: Field names whose control type is unambiguous regardless of operation -
#: used as a fallback before defaulting to plain text.
_GLOBAL_FIELDS: dict[str, FieldMeta] = {
    "date": ("Date", FieldType.date, None),
    "time": ("Time", FieldType.time, None),
    "datetime": ("Date & Time", FieldType.datetime, None),
}


def _label_from_field_name(field_name: str) -> str:
    return field_name.replace("_", " ").strip().title() or field_name


def resolve_field_meta(tool: str, operation: str, field_name: str) -> FieldMeta:
    """Look up (label, type, options) for one missing field name.

    Falls back, in order: operation-specific table -> global name table ->
    a plain text field labeled from the field name itself. Never raises -
    an unrecognized name is still renderable as a text box.
    """
    operation_fields = _OPERATION_FIELDS.get((tool, operation), {})
    if field_name in operation_fields:
        return operation_fields[field_name]
    if field_name in _GLOBAL_FIELDS:
        return _GLOBAL_FIELDS[field_name]
    return (_label_from_field_name(field_name), FieldType.text, None)
