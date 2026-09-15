import datetime as dt

from yuxi.utils.datetime_utils import UTC, duration_ms, format_utc_datetime


def test_format_utc_datetime_treats_naive_database_value_as_utc():
    value = dt.datetime(2026, 8, 14, 16, 23, 2, 398742)

    assert format_utc_datetime(value) == "2026-08-14T16:23:02.398742Z"


def test_format_utc_datetime_converts_aware_value_to_utc():
    value = dt.datetime(2026, 8, 15, 0, 23, tzinfo=dt.timezone(dt.timedelta(hours=8)))

    assert format_utc_datetime(value) == "2026-08-14T16:23:00Z"
    assert format_utc_datetime(value.astimezone(UTC)) == "2026-08-14T16:23:00Z"


def test_duration_ms_returns_non_negative_duration_or_none():
    start = dt.datetime(2026, 9, 4, 8, 0, 0)

    assert duration_ms(start, start + dt.timedelta(milliseconds=1234)) == 1234
    assert duration_ms(start, start - dt.timedelta(milliseconds=1)) is None
    assert duration_ms(None, start) is None
    assert duration_ms(start, None) is None
