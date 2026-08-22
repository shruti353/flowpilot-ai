from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.utils.datetime_parser import DatetimeNormalizationError, normalize_datetime

TZ = "Asia/Kolkata"
# Fixed reference "now" so relative expressions resolve deterministically,
# regardless of when the test suite actually runs.
REFERENCE_NOW = datetime(2026, 8, 22, 9, 0, 0, tzinfo=ZoneInfo(TZ))


def test_normalizes_tomorrow_at_3pm_to_a_concrete_datetime():
    result = normalize_datetime("tomorrow at 3 PM", TZ, reference_now=REFERENCE_NOW)

    assert result == datetime(2026, 8, 23, 15, 0, 0, tzinfo=ZoneInfo(TZ))
    assert result.tzinfo is not None


def test_normalizes_an_explicit_iso_like_string():
    result = normalize_datetime("2026-08-25 14:30", TZ, reference_now=REFERENCE_NOW)

    assert result.year == 2026
    assert result.month == 8
    assert result.day == 25
    assert result.hour == 14
    assert result.minute == 30


def test_rejects_unparseable_text():
    with pytest.raises(DatetimeNormalizationError):
        normalize_datetime("gibberish nonsense", TZ, reference_now=REFERENCE_NOW)


def test_rejects_blank_value():
    with pytest.raises(DatetimeNormalizationError):
        normalize_datetime("   ", TZ, reference_now=REFERENCE_NOW)


def test_rejects_invalid_timezone():
    with pytest.raises(DatetimeNormalizationError):
        normalize_datetime("tomorrow at 3 PM", "Not/A_Real_Zone", reference_now=REFERENCE_NOW)
