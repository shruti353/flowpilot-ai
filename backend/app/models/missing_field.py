"""Typed metadata for a single missing required field on an action.

The LLM only ever reports *names* of missing fields (see
`Action.missing_information` in app/models/action.py) - it has no notion of
what kind of input control a name like "datetime" or "title" implies. This
module defines that typed contract deterministically, so the frontend can
render the right control (date/time picker, textbox, number, select) instead
of a plain text prompt.
"""

from enum import Enum

from pydantic import BaseModel, Field


class FieldType(str, Enum):
    text = "text"
    date = "date"
    time = "time"
    datetime = "datetime"
    number = "number"
    select = "select"


class MissingFieldSpec(BaseModel):
    """Describes one missing field well enough to render an input for it."""

    field: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1)
    type: FieldType
    required: bool = True
    options: list[str] | None = Field(
        default=None,
        description="Allowed values, present only when type is 'select'.",
    )
