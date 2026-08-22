"""Deterministic execution-time date/time normalization.

Turns a natural-language expression like "tomorrow at 3 PM" into a
concrete, timezone-aware datetime. The LLM is never asked what "today"
is and never supplies the reference point - this module always resolves
relative expressions against the real wall-clock time (or an explicitly
injected reference, for tests) plus the configured FlowPilot timezone.

If an expression can't be parsed unambiguously, `normalize_datetime`
raises `DatetimeNormalizationError` - the caller must treat that as an
execution failure, never as license to invent a time.
"""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import dateparser


class DatetimeNormalizationError(Exception):
    """Raised when a raw datetime expression cannot be safely resolved."""

    def __init__(self, raw_value: str, message: str) -> None:
        self.raw_value = raw_value
        self.message = message
        super().__init__(message)


def normalize_datetime(
    raw_value: str,
    timezone_name: str,
    reference_now: datetime | None = None,
) -> datetime:
    """Parse `raw_value` into a concrete, timezone-aware datetime.

    `reference_now` pins the "current moment" relative expressions like
    "tomorrow" resolve against. It defaults to the real current time in
    `timezone_name` - tests pass a fixed value instead so results are
    reproducible.
    """
    if not raw_value or not raw_value.strip():
        raise DatetimeNormalizationError(raw_value, "No datetime value was provided.")

    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise DatetimeNormalizationError(
            raw_value, f"Configured timezone '{timezone_name}' is invalid: {exc}"
        ) from exc

    reference = reference_now if reference_now is not None else datetime.now(tz)
    # dateparser's RELATIVE_BASE must be naive wall-clock time in the
    # target timezone, not a tz-aware datetime.
    naive_reference = reference.replace(tzinfo=None)

    parsed = dateparser.parse(
        raw_value,
        settings={
            "TIMEZONE": timezone_name,
            "TO_TIMEZONE": timezone_name,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "RELATIVE_BASE": naive_reference,
            "PREFER_DATES_FROM": "future",
        },
    )

    if parsed is None:
        raise DatetimeNormalizationError(
            raw_value, f"Could not parse '{raw_value}' into a concrete date/time."
        )

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)

    return parsed
