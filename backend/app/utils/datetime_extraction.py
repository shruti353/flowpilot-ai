"""Deterministic date/time PRESENCE detection from free text.

Distinct from app.utils.datetime_parser.normalize_datetime (which resolves
an expression ALREADY known to be a date/time into a concrete datetime):
this module's job is to decide whether the user's own words actually
contained a date reference and/or a time reference at all, independently of
each other. Nothing downstream may fall back to "today"/"tomorrow" or any
other default when the user said neither - a local LLM will happily
hallucinate a plausible-looking date even when its prompt says not to (see
app/prompts/planner_prompt.py). app/agent/nodes/enrich_datetime.py uses this
as the deterministic authority instead of trusting the LLM's own claim about
what it was or wasn't given.
"""

import re

from dateparser.search import search_dates

#: Matches an explicit clock-time expression: "3pm", "3 PM", "9:30am",
#: "15:00", "noon", "midnight". Deliberately does NOT match bare numbers
#: (e.g. "3") - those are too ambiguous with unrelated digits in a sentence
#: to safely treat as a time.
_TIME_PATTERN = re.compile(
    r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b|\b\d{1,2}:\d{2}(:\d{2})?\b|\bnoon\b|\bmidnight\b",
    re.IGNORECASE,
)

#: A connector word ("at 3pm", "@3pm") immediately before a time match -
#: stripped along with the time phrase so it doesn't leak into the
#: remaining text handed to the date search below.
_TRAILING_CONNECTOR = re.compile(r"(at|@)\s*$", re.IGNORECASE)


def extract_date_and_time_phrases(text: str) -> tuple[str | None, str | None]:
    """Find a date phrase and a time phrase independently in `text`.

    Returns (date_phrase, time_phrase); either is None when that kind of
    information was not actually present - never a guess, and never a
    default like "today". The two are detected independently so "at 3 PM"
    (time only), "tomorrow" (date only), "tomorrow at 3 PM" (both), and
    plain text with neither all come back with the right shape.
    """
    if not text:
        return None, None

    time_match = _TIME_PATTERN.search(text)
    time_phrase = time_match.group(0) if time_match else None

    text_without_time = text
    if time_match:
        start, end = time_match.span()
        prefix = _TRAILING_CONNECTOR.sub("", text[:start])
        text_without_time = prefix + text[end:]

    date_matches = search_dates(text_without_time, settings={"PREFER_DATES_FROM": "future"})
    date_phrase = date_matches[0][0].strip() if date_matches else None

    return date_phrase, time_phrase
