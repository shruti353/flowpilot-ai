"""Tests for the deterministic date/time presence detector that backs
ENRICH_DATETIME's create_event handling (app/agent/nodes/enrich_datetime.py).

This is the fix for the reported bug: a request with no date reference at
all must never produce a fabricated "tomorrow", and date/time presence must
be detected independently of each other (one, the other, both, or neither).
"""

from app.utils.datetime_extraction import extract_date_and_time_phrases


def test_no_date_or_time_mentioned_extracts_neither():
    date_phrase, time_phrase = extract_date_and_time_phrases("Schedule a meeting with the AI team.")
    assert date_phrase is None
    assert time_phrase is None


def test_time_only_extracts_time_but_not_date():
    date_phrase, time_phrase = extract_date_and_time_phrases(
        "Schedule a meeting with the AI team at 3 PM."
    )
    assert date_phrase is None
    assert time_phrase == "3 PM"


def test_date_only_extracts_date_but_not_time():
    date_phrase, time_phrase = extract_date_and_time_phrases(
        "Schedule a meeting with the AI team tomorrow."
    )
    assert date_phrase == "tomorrow"
    assert time_phrase is None


def test_date_and_time_both_extracted():
    date_phrase, time_phrase = extract_date_and_time_phrases(
        "Schedule a meeting with the AI team tomorrow at 3 PM."
    )
    assert date_phrase == "tomorrow"
    assert time_phrase == "3 PM"


def test_absolute_date_and_24_hour_time():
    date_phrase, time_phrase = extract_date_and_time_phrases(
        "Schedule a meeting with the AI team on 2026-09-15 at 10:00."
    )
    assert date_phrase == "2026-09-15"
    assert time_phrase == "10:00"


def test_weekday_name_is_recognized_as_a_date():
    date_phrase, time_phrase = extract_date_and_time_phrases(
        "Schedule a meeting with the AI team on Friday at 9:30am."
    )
    assert date_phrase == "on Friday"
    assert time_phrase == "9:30am"


def test_empty_text_extracts_neither():
    assert extract_date_and_time_phrases("") == (None, None)
